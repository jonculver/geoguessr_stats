import json
import argparse
import os
from enum import Enum
from geoguessr.geoguessr import Geoguessr
from geoguessr.user import PlayerData

def enum_serializer(obj):
    """Custom JSON serializer for objects containing enums."""
    if isinstance(obj, Enum):
        return obj.value
    return obj.__dict__

def main():
    parser = argparse.ArgumentParser(description="Fetch GeoGuessr games for a user.")
    parser.add_argument("username", type=str, help="Username to fetch token for")
    parser.add_argument("--max-games", type=int, default=1000, help="Maximum number of games to query (default: 1000)")
    parser.add_argument("--overwrite", action="store_true", help="Overwrite existing data files")
    args = parser.parse_args()

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

    geo = Geoguessr(username, token, user_data.last_challenge_seed(), user_data.last_duel_id(), max_games)

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


if __name__ == "__main__":
    main()
