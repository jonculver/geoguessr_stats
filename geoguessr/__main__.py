import json
import argparse
import os
import sys
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from geoguessr.geoguessr import Geoguessr
from geoguessr.user import PlayerData, RankedDuelsSummary
from geoguessr.game import GameMode
from geoguessr.countries import CountryStats, country_code_to_name, name_to_country_code

def enum_serializer(obj):
    """Custom JSON serializer for objects containing enums."""
    if isinstance(obj, Enum):
        return obj.value
    return obj.__dict__

def fetch_command(args):
    """Fetch GeoGuessr games for a user."""
    username = args.username
    max_games = args.max_games
    
    # Load token from users.json
    with open("users.json", "r") as f:
        users = json.load(f)
    if username not in users:
        print(f"Username '{username}' not found in users.json.")
        return
    token = users[username]
    # Ensure output directory exists before any code that may read it
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    if not args.overwrite:
        user_data = PlayerData(username)
    else:
        user_data = PlayerData("")  # Empty data

    geo = Geoguessr(
        username,
        token,
        user_data.last_challenge_seed(),
        user_data.last_ranked_duel_id(),
        user_data.last_unranked_duel_id(),
        user_data.last_team_duel_id(),
        max_games,
    )

    # Append player data to geo data to keep reverse chronological order
    daily_challenge_games = geo.daily_challenge_games + user_data.daily_challenge_games
    ranked_duels = geo.ranked_duel_games + user_data.ranked_duel_games
    unranked_duels = geo.unranked_duel_games + user_data.unranked_duel_games
    ranked_team_duels = {}

    teammates = set(geo.ranked_team_duel_games.keys()).union(set(user_data.ranked_team_duel_games.keys()))
    for teammate in teammates:
        ranked_team_duels[teammate] = geo.ranked_team_duel_games.get(teammate, []) + user_data.ranked_team_duel_games.get(teammate, []) 
        
    # `output_dir` already created above

    # Save Daily challenge and Duel games
    print(f"Saving {len(daily_challenge_games)} daily challenge games")
    dc_file = os.path.join(output_dir, f"{username}_daily_challenge.json")
    with open(dc_file, "w") as f:
        json.dump(daily_challenge_games, f, default=enum_serializer, indent=2)

    print(f"Saving {len(ranked_duels)} ranked duel games")
    duel_file = os.path.join(output_dir, f"{username}_ranked_duels.json")
    with open(duel_file, "w") as f:
        json.dump(ranked_duels, f, default=enum_serializer, indent=2)

    print(f"Saving {len(unranked_duels)} unranked duel games")
    unranked_file = os.path.join(output_dir, f"{username}_unranked_duels.json")
    with open(unranked_file, "w") as f:
        json.dump(unranked_duels, f, default=enum_serializer, indent=2)

    # Save Team Duel games separately for each teammate
    for teammate, games in ranked_team_duels.items():
        print(f"Saving {len(games)} ranked team duel games with teammate '{teammate}'")
        team_duel_output_path = os.path.join(output_dir, f"{username}_{teammate}_ranked_team_duels.json")
        with open(team_duel_output_path, "w") as f:
            json.dump(games, f, default=enum_serializer, indent=2)

def display_command(args):
    """Display player data summary."""
    # Load player data
    player_data = PlayerData(args.player)

    if args.country:
        # Check country code or name validity
        if len(args.country) == 2:
            country_code = args.country.upper()
            country_name = country_code_to_name(args.country)
            if country_name == "Unknown Country":
                print(f"Unknown country code: {args.country}")
                sys.exit(1)
        else:
            country_code = name_to_country_code(args.country)
            if country_code == "Unknown":
                print(f"Unknown country name: {args.country}")
                sys.exit(1)
        
        # Print summary of rounds played in the specified country
        rounds_by_country = player_data.get_country_rounds(args.teammate, args.game_mode)
        country_stats = CountryStats.from_rounds(
            country_code=country_code,
            rounds=rounds_by_country.get(country_code, [])
        )
        print(f"Country stats for {args.player} {'and ' + args.teammate if args.teammate else ''}")
        print(f"  Mode: {args.game_mode if args.game_mode else 'All'}")
        print(f"  {country_stats}")
        return
    
    if args.teammate:
        games = player_data.ranked_team_duel_games.get(args.teammate, [])
    else:
        games = player_data.ranked_duel_games
    
    if args.game_mode:
        games = [game for game in games if game.mode.value == args.game_mode]

    summary = RankedDuelsSummary.from_games(games)
    print(f"Ranked Duel Summary for {args.player} {'and ' + args.teammate if args.teammate else ''}")
    print(f"  Mode: {args.game_mode if args.game_mode else 'All'}")
    print(f"  {summary}")


def _parse_analyse_mode(mode: Optional[str]) -> Optional[GameMode]:
    if not mode:
        return None
    mode_norm = mode.strip().lower()
    if mode_norm == "moving":
        return GameMode.MOVING
    if mode_norm in {"nm", "no_move", "nomove"}:
        return GameMode.NO_MOVE
    if mode_norm == "nmpz":
        return GameMode.NMPZ
    raise ValueError(f"Unknown mode: {mode}")


def analyse_command(args):
    """Analyse player data."""

    def _parse_game_timestamp(game) -> float:
        """Return a sortable timestamp (seconds since epoch) for a duel game."""
        ts = getattr(game, "start_time", "") or getattr(game, "time", "") or ""
        if not ts:
            return float("-inf")
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return float("-inf")

    analysis_type = args.type
    if analysis_type is not None and analysis_type != "region":
        print(f"Unknown analysis type: {analysis_type}")
        sys.exit(1)

    player_data = PlayerData(args.username)

    include = args.include
    if include == "ranked":
        duel_games = list(player_data.ranked_duel_games)
    elif include == "unranked":
        duel_games = list(player_data.unranked_duel_games)
    else:
        duel_games = list(player_data.ranked_duel_games) + list(player_data.unranked_duel_games)

    mode = _parse_analyse_mode(args.mode)
    if mode:
        duel_games = [game for game in duel_games if game.mode == mode]

    if args.max_games is not None:
        if args.max_games <= 0:
            print("--max-games must be a positive integer")
            sys.exit(1)
        # Ensure we always take the most recent games (especially for --include both).
        duel_games.sort(key=_parse_game_timestamp, reverse=True)
        duel_games = duel_games[: args.max_games]

    rounds_by_country: dict[str, list] = {}
    for game in duel_games:
        for duel_round in game.rounds:
            cc = (duel_round.country_code or "").upper() or "??"
            rounds_by_country.setdefault(cc, []).append(duel_round)

    stats = [CountryStats.from_rounds(cc, rounds) for cc, rounds in rounds_by_country.items()]

    if args.min_rounds is not None:
        if args.min_rounds < 0:
            print("--min-rounds must be >= 0")
            sys.exit(1)
        stats = [s for s in stats if s.total_rounds >= args.min_rounds]

    if analysis_type is None:
        def avg_damage_taken(s: CountryStats) -> float:
            return (s.total_damage_taken / s.total_rounds) if s.total_rounds else 0.0

        stats.sort(key=avg_damage_taken, reverse=True)

        print(f"Country damage taken (avg) for {args.username}")
        print(f"  Include: {include}")
        print(f"  Mode: {mode.value if mode else 'All'}")
        print(f"  Games: {len(duel_games)}")
        print(f"  Countries: {len(stats)}")

        for s in stats:
            avg_taken = (s.total_damage_taken / s.total_rounds) if s.total_rounds else 0.0
            print(
                f"  {s.country_code} {s.name}: avg_taken={avg_taken:.2f} "
                f"rounds={s.total_rounds} win%={s.win_percentage}"
            )
        return

    # --type region
    stats.sort(key=lambda s: s.total_rounds, reverse=True)

    print(f"Region analysis for {args.username}")
    print(f"  Include: {include}")
    print(f"  Mode: {mode.value if mode else 'All'}")
    print(f"  Games: {len(duel_games)}")
    print(f"  Regions: {len(stats)}")

    for s in stats:
        print(
            f"  {s.country_code} {s.name}: rounds={s.total_rounds} win%={s.win_percentage} "
            f"mean_dist_m={s.mean_distance} mean_time_s={s.mean_time}"
        )

def main():
    parser = argparse.ArgumentParser(
        description="GeoGuessr stats CLI",
        prog="python -m geoguessr"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")
    
    # Fetch subcommand
    fetch_parser = subparsers.add_parser("fetch", help="Fetch GeoGuessr games for a user")
    fetch_parser.add_argument("username", type=str, help="Username to fetch token for")
    fetch_parser.add_argument("--max-games", type=int, default=1000, help="Maximum number of games to query (default: 1000)")
    fetch_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing data files")
    fetch_parser.set_defaults(func=fetch_command)
    
    # Display subcommand
    display_parser = subparsers.add_parser("display", help="Display player data summary")
    display_parser.add_argument("player", help="Player name or ID to filter by")
    display_parser.add_argument("-t", "--teammate", help="Optional teammate name", default=None)
    display_parser.add_argument("-c", "--country", help="Optional country code or name", default=None)
    display_parser.add_argument("-m", "--game-mode", help="Game mode", choices=[mode.value for mode in GameMode], default=None)
    display_parser.set_defaults(func=display_command)

    # Analyse subcommand
    analyse_parser = subparsers.add_parser("analyse", help="Analyse player data")
    analyse_parser.add_argument("username", type=str, help="Username to analyse")
    analyse_parser.add_argument("-type", "--type", choices=["region"], default=None, help="Analysis type (currently only: region)")
    analyse_parser.add_argument("-mode", "--mode", choices=["moving", "nm", "nmpz"], default=None, help="Game mode filter")
    analyse_parser.add_argument("-include", "--include", choices=["ranked", "unranked", "both"], default="both", help="Which games to include")
    analyse_parser.add_argument("--max-games", type=int, default=None, help="Limit analysis to the most recent N games")
    analyse_parser.add_argument("--min-rounds", type=int, default=None, help="Only include countries with at least this many rounds")
    analyse_parser.set_defaults(func=analyse_command)
    
    args = parser.parse_args()
    
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
