import os
import sys
import json

from game import GeoguessrDuelGame, GeoguessrChallengeGame, GameType

class User:
    def __init__(self, username: str):
        self.username = username
        self.daily_challenge_games: list[GeoguessrChallengeGame] = []
        self.ranked_duel_games: list[GeoguessrDuelGame] = []
        self.ranked_team_duel_games: dict[str: list[GeoguessrDuelGame]] = {}

        self._get_daily_challenge_games()
        self._get_ranked_duel_games()
        self._get_ranked_team_duel_games()

    def _get_daily_challenge_games(self):
        """
        Read data from output/USERNAME_daily_challenge.json and populate daily_challenge_games
        """
        filepath = f"output/{self.username}_daily_challenge.json"
        if not os.path.exists(filepath):
            return
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        for item in raw_data:
            game = GeoguessrChallengeGame(
                game_type=item.get('game_type', GameType.DAILY_CHALLENGE),
                time=item.get('time', ""),
                challenge_token=item.get('challenge_token', ""),
                points=item.get('points', 0)
            )
            self.daily_challenge_games.append(game)

    def _get_ranked_duel_games(self):
        """
        Read data from output/USERNAME_ranked_duels.json and populate ranked_duel_games
        """
        filepath = f"output/{self.username}_ranked_duels.json"
        if not os.path.exists(filepath):
            return
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
        for item in raw_data:
            self.ranked_duel_games.append(GeoguessrDuelGame.from_json(item) )
    
    def _get_ranked_team_duel_games(self):
        """
        Read data from output/USERNAME_TEAMMATE_ranked_team_duels.json and populate ranked_team_duel_games
        """
        dirpath = "output"
        for filename in os.listdir(dirpath):
            if filename.startswith(f"{self.username}_") and filename.endswith("_ranked_team_duels.json"):
                teammate = filename[len(self.username)+1:-len("_ranked_team_duels.json")]
                filepath = os.path.join(dirpath, filename)
                with open(filepath, 'r', encoding='utf-8') as f:
                    raw_data = json.load(f)
                games = []
                for item in raw_data:
                    games.append(GeoguessrDuelGame.from_json(item))
                self.ranked_team_duel_games[teammate] = games

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python geoguessr/user.py USERNAME")
        sys.exit(1)
    user = sys.argv[1]
    geouser = User(user)

    print(f"User: {geouser.username}")
    print(f"  Daily Challenge Games: {len(geouser.daily_challenge_games)}")
    print(f"  Daily Challenge Average: {sum(game.points for game in geouser.daily_challenge_games) / len(geouser.daily_challenge_games) if geouser.daily_challenge_games else 0:.2f}")
    print(f"  Ranked Duel Games: {len(geouser.ranked_duel_games)}")
    for teammate, games in geouser.ranked_team_duel_games.items():
        print(f"  Ranked Team Duel Games with {teammate}: {len(games)}")