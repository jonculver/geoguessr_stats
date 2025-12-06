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

    geo = Geoguessr(username, token)
    games = geo.get_games(max_games=max_games)

    for k, v in games.items():
        print(f"{k}: {len(v)} games")

    output_dir = "output"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"{username}_games.json")
    with open(output_path, "w") as f:
        json.dump(games, f, default=lambda o: o.__dict__, indent=2)

if __name__ == "__main__":
    main()
