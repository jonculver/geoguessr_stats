import json
import argparse
import os
from geoguessr.geoguessr import Geoguessr

def main():
    parser = argparse.ArgumentParser(description="Fetch GeoGuessr games for a user.")
    parser.add_argument("username", type=str, help="Username to fetch token for")
    parser.add_argument("--max-games", type=int, default=50, help="Maximum number of games to query (default: 50)")
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

    geo = Geoguessr(username, token, max_games=max_games)

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)

    # Save Daily challenge and Duel games
    print(f"Saving {len(geo.daily_challenge_games)} daily challenge games")
    dc_file = os.path.join(output_dir, f"{username}_daily_challenge.json")
    with open(dc_file, "w") as f:
        json.dump(geo.daily_challenge_games, f, default=lambda o: o.__dict__, indent=2)

    print(f"Saving {len(geo.ranked_duel_games)} ranked duel games")
    duel_file = os.path.join(output_dir, f"{username}_ranked_duels.json")
    with open(duel_file, "w") as f:
        json.dump(geo.ranked_duel_games, f, default=lambda o: o.__dict__, indent=2)

    # Save Team Duel games separately for each teammate
    for teammate, games in geo.ranked_team_duel_games.items():
        print(f"Saving {len(games)} ranked team duel games with teammate '{teammate}'")
        team_duel_output_path = os.path.join(output_dir, f"{username}_{teammate}_ranked_team_duels.json")
        with open(team_duel_output_path, "w") as f:
            json.dump(games, f, default=lambda o: o.__dict__, indent=2)


if __name__ == "__main__":
    main()
