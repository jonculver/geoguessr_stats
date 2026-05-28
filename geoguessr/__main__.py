import json
import argparse
import os
import sys
from datetime import datetime, timezone
import signal
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
        user_data.last_standard_game_token(),
        user_data.last_ranked_duel_id(),
        user_data.last_unranked_duel_id(),
        user_data.last_team_duel_id(),
        max_games,
    )

    # Append player data to geo data to keep reverse chronological order
    daily_challenge_games = geo.daily_challenge_games + user_data.daily_challenge_games
    standard_games = geo.standard_games + getattr(user_data, "standard_games", [])
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

    print(f"Saving {len(standard_games)} standard games")
    standard_file = os.path.join(output_dir, f"{username}_standard_games.json")
    with open(standard_file, "w") as f:
        json.dump(standard_games, f, default=enum_serializer, indent=2)

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


def country_command(args):
    """List duel rounds for a given country."""
    username = args.username
    country = args.country
    max_games = args.max_games
    max_days = getattr(args, "max_days", None)
    include = args.include
    mode = _parse_analyse_mode(args.mode)
    both_correct = bool(getattr(args, "both_correct", False))
    min_net = int(getattr(args, "min_net", 0) or 0)

    if not country or len(country.strip()) != 2:
        print("Country must be a 2-letter country code (e.g. 'US')")
        sys.exit(1)

    target_cc = country.strip().upper()
    player_data = PlayerData(username)

    if isinstance(include, str) and include.startswith("team:"):
        teammate = include.split(":", 1)[1].strip()
        team_games = list(player_data.ranked_team_duel_games.get(teammate, []))
        duel_games: list[tuple[object, str]] = [(g, f"Team-{teammate}") for g in team_games]
    elif include == "ranked":
        duel_games = [(g, "Ranked") for g in list(player_data.ranked_duel_games)]
    elif include == "unranked":
        duel_games = [(g, "Unranked") for g in list(player_data.unranked_duel_games)]
    elif include == "both" or not include:
        duel_games = [(g, "Ranked") for g in list(player_data.ranked_duel_games)] + [
            (g, "Unranked") for g in list(player_data.unranked_duel_games)
        ]
    else:
        print(f"Unknown --include value: {include}")
        sys.exit(1)

    if mode is not None:
        duel_games = [(g, t) for (g, t) in duel_games if getattr(g, "mode", None) == mode]

    if max_days is not None:
        if max_days <= 0:
            print("--max-days must be a positive integer")
            sys.exit(1)

    if max_games is not None:
        if max_games <= 0:
            print("--max-games must be a positive integer")
            sys.exit(1)

    if min_net < -5000 or min_net > 5000:
        print("--min-net must be between -5000 and 5000", file=sys.stderr)
        sys.exit(1)

    def multiplier_fields_look_missing(duel_round) -> bool:
        try:
            team_multi = float(getattr(duel_round, "team_multiplier", 1.0) or 1.0)
            opp_multi = float(getattr(duel_round, "opponent_multiplier", 1.0) or 1.0)
        except Exception:
            team_multi = 1.0
            opp_multi = 1.0
        team_active = bool(getattr(duel_round, "team_active_multiplier", False))
        opp_active = bool(getattr(duel_round, "opponent_active_multiplier", False))
        return team_multi == 1.0 and opp_multi == 1.0 and (not team_active) and (not opp_active)

    def decode_pano_id(pano_id: str) -> str:
        """Decode stored pano_id.

        Our JSON often stores pano IDs hex-encoded; decode to UTF-8 when it looks like hex.
        """
        if not pano_id:
            return ""
        s = pano_id.strip()
        if len(s) % 2 != 0:
            return s
        try:
            int(s, 16)
        except Exception:
            return s
        try:
            return bytes.fromhex(s).decode("utf-8")
        except Exception:
            return s

    def streetview_url_from_pano_id(pano_id: str) -> str:
        pano = decode_pano_id(pano_id)
        if not pano:
            return ""
        return f"https://www.google.com/maps/@?api=1&map_action=pano&pano={pano}"

    def parse_ts(ts: str) -> float:
        if not ts:
            return float("-inf")
        try:
            import re

            s = ts.replace("Z", "+00:00")
            # Python 3.9 can choke on fractional seconds with <6 digits (e.g. `.73`).
            m = re.match(r"^(.*T\d\d:\d\d:\d\d)\.(\d+)([+-]\d\d:\d\d)$", s)
            if m:
                base, frac, offset = m.group(1), m.group(2), m.group(3)
                frac = (frac[:6]).ljust(6, "0")
                s = f"{base}.{frac}{offset}"
            return datetime.fromisoformat(s).timestamp()
        except Exception:
            return float("-inf")

    def multiplier_safe(value: object) -> float:
        try:
            f = float(value)  # type: ignore[arg-type]
        except Exception:
            return 1.0
        return f if f > 0 else 1.0

    def net_damage_normalized(duel_round) -> float:
        taken = float(getattr(duel_round, "damage_taken", 0) or 0)
        dealt = float(getattr(duel_round, "damage_dealt", 0) or 0)
        opp_multi = multiplier_safe(getattr(duel_round, "opponent_multiplier", 1.0))
        team_multi = multiplier_safe(getattr(duel_round, "team_multiplier", 1.0))
        return (taken / opp_multi) - (dealt / team_multi)

    def game_ts(game) -> float:
        ts = getattr(game, "start_time", "") or getattr(game, "time", "") or ""
        parsed = parse_ts(ts)
        if parsed != float("-inf"):
            return parsed
        # Fallback: use the most recent round start time.
        round_ts = [parse_ts(getattr(r, "start_time", "") or "") for r in getattr(game, "rounds", []) or []]
        return max(round_ts) if round_ts else float("-inf")

    if max_days is not None:
        cutoff = datetime.now(timezone.utc).timestamp() - (float(max_days) * 86400.0)
        duel_games = [(g, t) for (g, t) in duel_games if game_ts(g) >= cutoff]

    if max_games is not None:
        duel_games = sorted(duel_games, key=game_ts, reverse=True)[:max_games]

    # Heuristic warning: older output JSON (fetched before multiplier support) will load with
    # default multiplier values (1.0 / False), which makes normalized net misleading.
    sample_rounds = []
    for g, _t in duel_games[: min(len(duel_games), 25)]:
        sample_rounds.extend((getattr(g, "rounds", []) or [])[:10])
    if sample_rounds:
        missing = sum(1 for r in sample_rounds if multiplier_fields_look_missing(r))
    else:
        missing = 0
    if sample_rounds and missing:
        print(
            f"Warning: duel multipliers appear missing for {missing}/{len(sample_rounds)} sampled rounds; "
            "run `python -m geoguessr fetch <user> --overwrite --max-games N` to backfill.",
            file=sys.stderr,
        )

    def has_two_guess_locations(duel_round) -> bool:
        guess_locations = getattr(duel_round, "guess_locations", None) or {}
        if not isinstance(guess_locations, dict):
            return False
        valid = 0
        for info in guess_locations.values():
            if not isinstance(info, dict):
                continue
            lat = info.get("lat")
            lng = info.get("lng")
            try:
                float(lat)
                float(lng)
            except Exception:
                continue
            valid += 1
            if valid >= 2:
                return True
        return False

    def round_all_players_correct_country(duel_round) -> bool:
        """True iff at least two players guessed the panorama country for this round."""
        correct_cc = (getattr(duel_round, "country_code", "") or "").upper()
        if not correct_cc or correct_cc == "??":
            return False

        guess_locations = getattr(duel_round, "guess_locations", None) or {}
        guessed_ccs: list[str] = []
        if isinstance(guess_locations, dict):
            for info in guess_locations.values():
                if not isinstance(info, dict):
                    continue
                g_cc = (info.get("country_code") or "").upper()
                if g_cc:
                    guessed_ccs.append(g_cc)

        if len(guessed_ccs) < 2:
            return False
        return all(g == correct_cc for g in guessed_ccs)

    rows: list[tuple[float, float, str]] = []
    for game, duel_type in duel_games:
        mode_value = getattr(game, "mode", None)
        if mode_value == GameMode.NO_MOVE:
            mode_display = "NM"
        elif mode_value == GameMode.MOVING:
            mode_display = "Moving"
        elif mode_value == GameMode.NMPZ:
            mode_display = "NMPZ"
        else:
            mode_display = "?"

        player_id = getattr(game, "player_id", "") or ""
        for i, duel_round in enumerate(getattr(game, "rounds", []) or [], start=1):
            if not has_two_guess_locations(duel_round):
                continue
            actual_cc = (getattr(duel_round, "country_code", "") or "").upper() or "??"
            if actual_cc != target_cc:
                continue
            if both_correct and not round_all_players_correct_country(duel_round):
                continue

            net_damage = net_damage_normalized(duel_round)
            if net_damage < min_net:
                continue
            pano_id = getattr(duel_round, "pano_id", "") or ""
            sv_url = streetview_url_from_pano_id(pano_id)
            start_time = getattr(duel_round, "start_time", "") or ""

            correct = "?"
            guess_locations = getattr(duel_round, "guess_locations", None) or {}
            if player_id and isinstance(guess_locations, dict):
                info = guess_locations.get(player_id)
                if isinstance(info, dict):
                    guessed_cc = (info.get("country_code") or "").upper()
                    if guessed_cc:
                        correct = "Y" if guessed_cc == actual_cc else "N"

            date = start_time.split("T", 1)[0] if start_time else ""
            game_id = getattr(game, 'game_id', '')
            game_url = f"https://www.geoguessr.com/duels/{game_id}" if game_id else ""
            net_display = int(round(net_damage))
            line = f"  {date} duel={duel_type} mode={mode_display} net={net_display} round={i} correct={correct}\n    {game_url}\n    {sv_url}\n"
            rows.append((net_damage, parse_ts(start_time), line))

    # Sort by net damage (highest first), then by time for stability.
    rows.sort(key=lambda r: (-r[0], r[1]))

    print(f"Duel rounds in {target_cc} for {username}")
    if both_correct:
        print("  Filter: both players guessed correct country")
    if min_net != 0:
        print(f"  Filter: net damage >= {min_net}")
    print(f"  Rounds: {len(rows)}")
    for _, __, line in rows:
        print(line)


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

    def _multiplier_safe(value: object) -> float:
        try:
            f = float(value)  # type: ignore[arg-type]
        except Exception:
            return 1.0
        return f if f > 0 else 1.0

    def _net_damage_normalized(duel_round) -> float:
        """Net damage adjusted for multipliers.

        taken is divided by opponent multiplier; dealt is divided by team multiplier.
        """
        taken = float(getattr(duel_round, "damage_taken", 0) or 0)
        dealt = float(getattr(duel_round, "damage_dealt", 0) or 0)
        opp_multi = _multiplier_safe(getattr(duel_round, "opponent_multiplier", 1.0))
        team_multi = _multiplier_safe(getattr(duel_round, "team_multiplier", 1.0))
        return (taken / opp_multi) - (dealt / team_multi)

    def _parse_game_timestamp(game) -> float:
        """Return a sortable timestamp (seconds since epoch) for a duel game."""
        ts = getattr(game, "start_time", "") or getattr(game, "time", "") or ""
        if not ts:
            return float("-inf")
        try:
            import re

            s = ts.replace("Z", "+00:00")
            m = re.match(r"^(.*T\d\d:\d\d:\d\d)\.(\d+)([+-]\d\d:\d\d)$", s)
            if m:
                base, frac, offset = m.group(1), m.group(2), m.group(3)
                frac = (frac[:6]).ljust(6, "0")
                s = f"{base}.{frac}{offset}"

            dt = datetime.fromisoformat(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except Exception:
            return float("-inf")

    analysis_type = args.type
    if analysis_type is not None and analysis_type not in {"region", "wrong-country", "win-percentage"}:
        print(f"Unknown analysis type: {analysis_type}")
        sys.exit(1)

    player_data = PlayerData(args.username)

    max_days = getattr(args, "max_days", None)

    include = args.include
    if isinstance(include, str) and include.startswith("team:"):
        teammate = include.split(":", 1)[1].strip()
        duel_games = list(player_data.ranked_team_duel_games.get(teammate, []))
    elif include == "ranked":
        duel_games = list(player_data.ranked_duel_games)
    elif include == "unranked":
        duel_games = list(player_data.unranked_duel_games)
    elif include == "both" or not include:
        duel_games = list(player_data.ranked_duel_games) + list(player_data.unranked_duel_games)
    else:
        print(f"Unknown --include value: {include}")
        sys.exit(1)

    mode = _parse_analyse_mode(args.mode)
    if mode:
        duel_games = [game for game in duel_games if game.mode == mode]

    if max_days is not None:
        if max_days <= 0:
            print("--max-days must be a positive integer")
            sys.exit(1)
        cutoff = datetime.now(timezone.utc).timestamp() - (float(max_days) * 86400.0)
        duel_games = [g for g in duel_games if _parse_game_timestamp(g) >= cutoff]

    if args.max_games is not None:
        if args.max_games <= 0:
            print("--max-games must be a positive integer")
            sys.exit(1)
        # Ensure we always take the most recent games (especially for --include both).
        duel_games.sort(key=_parse_game_timestamp, reverse=True)
        duel_games = duel_games[: args.max_games]

    def multiplier_fields_look_missing(duel_round) -> bool:
        try:
            team_multi = float(getattr(duel_round, "team_multiplier", 1.0) or 1.0)
            opp_multi = float(getattr(duel_round, "opponent_multiplier", 1.0) or 1.0)
        except Exception:
            team_multi = 1.0
            opp_multi = 1.0
        team_active = bool(getattr(duel_round, "team_active_multiplier", False))
        opp_active = bool(getattr(duel_round, "opponent_active_multiplier", False))
        return team_multi == 1.0 and opp_multi == 1.0 and (not team_active) and (not opp_active)

    sample_rounds = []
    for g in duel_games[: min(len(duel_games), 25)]:
        sample_rounds.extend((getattr(g, "rounds", []) or [])[:10])
    if sample_rounds:
        missing = sum(1 for r in sample_rounds if multiplier_fields_look_missing(r))
    else:
        missing = 0
    if sample_rounds and missing:
        print(
            f"Warning: duel multipliers appear missing for {missing}/{len(sample_rounds)} sampled rounds; "
            "run `python -m geoguessr fetch <user> --overwrite --max-games N` to backfill.",
            file=sys.stderr,
        )

    def has_two_guess_locations(duel_round) -> bool:
        guess_locations = getattr(duel_round, "guess_locations", None) or {}
        if not isinstance(guess_locations, dict):
            return False
        valid = 0
        for info in guess_locations.values():
            if not isinstance(info, dict):
                continue
            lat = info.get("lat")
            lng = info.get("lng")
            try:
                float(lat)
                float(lng)
            except Exception:
                continue
            valid += 1
            if valid >= 2:
                return True
        return False

    def _round_both_players_correct_country(duel_round) -> bool:
        """True iff both players guessed the panorama country for this round."""
        correct_cc = (getattr(duel_round, "country_code", "") or "").upper()
        if not correct_cc or correct_cc == "??":
            return False

        guess_locations = getattr(duel_round, "guess_locations", None) or {}
        guessed_ccs: list[str] = []
        if isinstance(guess_locations, dict):
            for info in guess_locations.values():
                if not isinstance(info, dict):
                    continue
                g_cc = (info.get("country_code") or "").upper()
                if g_cc:
                    guessed_ccs.append(g_cc)

        # Need at least two players with country codes.
        if len(guessed_ccs) < 2:
            return False
        return all(g == correct_cc for g in guessed_ccs)

    rounds_by_country: dict[str, list] = {}
    for game in duel_games:
        for duel_round in game.rounds:
            if not has_two_guess_locations(duel_round):
                continue
            cc = (duel_round.country_code or "").upper() or "??"
            if analysis_type == "region" and not _round_both_players_correct_country(duel_round):
                continue
            rounds_by_country.setdefault(cc, []).append(duel_round)

    stats = [CountryStats.from_rounds(cc, rounds) for cc, rounds in rounds_by_country.items()]

    if args.min_rounds is not None:
        if args.min_rounds < 0:
            print("--min-rounds must be >= 0")
            sys.exit(1)
        stats = [s for s in stats if s.total_rounds >= args.min_rounds]

    def avg_net_damage(s: CountryStats) -> float:
        rounds = rounds_by_country.get(s.country_code, [])
        if not rounds:
            return 0.0
        return sum(_net_damage_normalized(r) for r in rounds) / len(rounds)

    if analysis_type is None:
        stats.sort(key=avg_net_damage, reverse=True)

        print(f"Country net damage (avg taken/opponent_multi - dealt/team_multi) for {args.username}")
        print(f"  Include: {include}")
        print(f"  Mode: {mode.value if mode else 'All'}")
        print(f"  Games: {len(duel_games)}")
        print(f"  Countries: {len(stats)}")

        for idx, s in enumerate(stats, start=1):
            avg_net = avg_net_damage(s)
            print(
                f"  {idx} {s.country_code} {s.name}: avg_net={avg_net:.2f} "
                f"rounds={s.total_rounds} win%={s.win_percentage}"
            )
        return

    if analysis_type == "win-percentage":
        # Rank countries by the percentage of rounds won.
        # (This uses the existing CountryStats.win_percentage metric.)
        stats.sort(key=lambda s: (s.win_percentage, s.total_rounds, avg_net_damage(s)), reverse=True)

        print(f"Win-percentage analysis for {args.username}")
        print(f"  Include: {include}")
        print(f"  Mode: {mode.value if mode else 'All'}")
        print(f"  Games: {len(duel_games)}")
        print(f"  Countries: {len(stats)}")

        for idx, s in enumerate(stats, start=1):
            avg_net = avg_net_damage(s)
            print(
                f"  {idx} {s.country_code} {s.name}: avg_net={avg_net:.2f} "
                f"rounds={s.total_rounds} win%={s.win_percentage}"
            )
        return

    if analysis_type == "wrong-country":
        # Count how often the player's guessed country != the panorama country, grouped by panorama country.
        wrong_by_country: dict[str, int] = {}
        total_by_country: dict[str, int] = {}

        for game in duel_games:
            player_id = getattr(game, "player_id", "") or ""
            for duel_round in game.rounds:
                if not has_two_guess_locations(duel_round):
                    continue
                actual_cc = (getattr(duel_round, "country_code", "") or "").upper() or "??"
                if actual_cc == "??":
                    continue

                guess_locations = getattr(duel_round, "guess_locations", None) or {}
                if not isinstance(guess_locations, dict) or not player_id:
                    continue
                player_guess = guess_locations.get(player_id) or {}
                if not isinstance(player_guess, dict):
                    continue
                guessed_cc = (player_guess.get("country_code") or "").upper()
                if not guessed_cc:
                    continue

                total_by_country[actual_cc] = total_by_country.get(actual_cc, 0) + 1
                if guessed_cc != actual_cc:
                    wrong_by_country[actual_cc] = wrong_by_country.get(actual_cc, 0) + 1

        rows: list[tuple[str, int, int, float]] = []
        for cc, total in total_by_country.items():
            wrong = wrong_by_country.get(cc, 0)
            wrong_pct = (wrong * 100.0 / total) if total else 0.0
            rows.append((cc, wrong, total, wrong_pct))

        if args.min_rounds is not None:
            rows = [r for r in rows if r[2] >= args.min_rounds]

        # Worst -> best by wrong percentage; break ties by sample size.
        rows.sort(key=lambda r: (r[3], r[2]), reverse=True)

        print(f"Wrong-country analysis for {args.username}")
        print(f"  Include: {include}")
        print(f"  Mode: {mode.value if mode else 'All'}")
        print(f"  Games: {len(duel_games)}")
        print(f"  Countries: {len(rows)}")

        for idx, (cc, wrong, total, wrong_pct) in enumerate(rows, start=1):
            name = country_code_to_name(cc)
            print(f"  {idx} {cc} {name}: wrong%={wrong_pct:.1f} wrong={wrong} rounds={total}")
        return

    # --type region
    stats.sort(key=avg_net_damage, reverse=True)

    print(f"Region analysis for {args.username}")
    print(f"  Include: {include}")
    print(f"  Mode: {mode.value if mode else 'All'}")
    print(f"  Games: {len(duel_games)}")
    print(f"  Regions: {len(stats)}")

    for idx, s in enumerate(stats, start=1):
        avg_net = avg_net_damage(s)
        print(
            f"  {idx} {s.country_code} {s.name}: avg_net={avg_net:.2f} "
            f"rounds={s.total_rounds} win%={s.win_percentage}"
        )


def web_command(args):
    """Run a local web UI for analyse/country."""
    try:
        import uvicorn
    except Exception:
        print("Missing dependency: uvicorn. Run `pip install -r requirements.txt`.")
        sys.exit(1)

    if args.reload:
        uvicorn.run(
            "geoguessr.web.app:create_app",
            host=args.host,
            port=args.port,
            reload=True,
            factory=True,
        )
        return

    from geoguessr.web.app import create_app

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port)

def main():
    # Make piping to tools like `head` behave like typical Unix CLIs.
    try:
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)
    except Exception:
        pass

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

    # Country subcommand
    country_parser = subparsers.add_parser("country", help="List duel rounds for a country")
    country_parser.add_argument("username", type=str, help="Username to analyse")
    country_parser.add_argument("country", type=str, help="2-letter country code (e.g. US)")
    country_parser.add_argument(
        "--include",
        default="both",
        help="Which games to include: ranked | unranked | both | team:<teammate>",
    )
    country_parser.add_argument("-mode", "--mode", choices=["moving", "nm", "nmpz"], default=None, help="Game mode filter")
    country_parser.add_argument("--max-days", type=int, default=None, help="Only include games from the last N days")
    country_parser.add_argument("--max-games", type=int, default=None, help="Limit to the most recent N games")
    country_parser.add_argument(
        "--min-net",
        type=int,
        default=0,
        help="Minimum net damage taken (normalized by multipliers), between -5000 and 5000 (default: 0)",
    )
    country_parser.add_argument(
        "--both-correct",
        action="store_true",
        help="Only include rounds where both players guessed the correct country",
    )
    country_parser.set_defaults(func=country_command)

    # Analyse subcommand
    analyse_parser = subparsers.add_parser("analyse", help="Analyse player data")
    analyse_parser.add_argument("username", type=str, help="Username to analyse")
    analyse_parser.add_argument("-type", "--type", choices=["region", "wrong-country", "win-percentage"], default=None, help="Analysis type")
    analyse_parser.add_argument("-mode", "--mode", choices=["moving", "nm", "nmpz"], default=None, help="Game mode filter")
    analyse_parser.add_argument(
        "-include",
        "--include",
        default="both",
        help="Which games to include: ranked | unranked | both | team:<teammate>",
    )
    analyse_parser.add_argument("--max-games", type=int, default=None, help="Limit analysis to the most recent N games")
    analyse_parser.add_argument("--max-days", type=int, default=None, help="Only include games from the last N days")
    analyse_parser.add_argument("--min-rounds", type=int, default=None, help="Only include countries with at least this many rounds")
    analyse_parser.set_defaults(func=analyse_command)

    # Web UI subcommand
    web_parser = subparsers.add_parser("web", help="Run a local web UI")
    web_parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    web_parser.add_argument("--port", type=int, default=8000, help="Port to bind (default: 8000)")
    web_parser.add_argument("--reload", action="store_true", help="Auto-reload on code changes")
    web_parser.set_defaults(func=web_command)
    
    args = parser.parse_args()
    
    if hasattr(args, 'func'):
        try:
            args.func(args)
        except BrokenPipeError:
            # Common when piping to `head`/`tail` and the pipe closes early.
            return
    else:
        parser.print_help()

if __name__ == "__main__":
    main()
