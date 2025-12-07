import json
import argparse
import os
import sys
from enum import Enum
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

    if not args.overwrite:
        user_data = PlayerData(username)
    else:
        user_data = PlayerData("")  # Empty data

    geo = Geoguessr(username, token, user_data.last_challenge_seed(), user_data.last_ranked_duel_id(), user_data.last_team_duel_id(), max_games)

    # Append player data to geo data to keep reverse chronological order
    daily_challenge_games = geo.daily_challenge_games + user_data.daily_challenge_games
    ranked_duels = geo.ranked_duel_games + user_data.ranked_duel_games
    ranked_team_duels = {}

    teammates = set(geo.ranked_team_duel_games.keys()).union(set(user_data.ranked_team_duel_games.keys()))
    for teammate in teammates:
        ranked_team_duels[teammate] = geo.ranked_team_duel_games.get(teammate, []) + user_data.ranked_team_duel_games.get(teammate, []) 
        
    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    # Save Daily challenge and Duel games
    print(f"Saving {len(daily_challenge_games)} daily challenge games")
    dc_file = os.path.join(output_dir, f"{username}_daily_challenge.json")
    with open(dc_file, "w") as f:
        json.dump(daily_challenge_games, f, default=enum_serializer, indent=2)

    print(f"Saving {len(ranked_duels)} ranked duel games")
    duel_file = os.path.join(output_dir, f"{username}_ranked_duels.json")
    with open(duel_file, "w") as f:
        json.dump(ranked_duels, f, default=enum_serializer, indent=2)

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
    
    args = parser.parse_args()
    
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
