import os
import sys
import json
import argparse

from dataclasses import dataclass

from geoguessr.game import GeoguessrDuelGame, GeoguessrChallengeGame, GameType, GeoguessrDuelRound, GameMode
from geoguessr.countries import CountryStats, country_code_to_name, name_to_country_code

@dataclass
class RankedDuelsSummary:
    total_games: int
    total_moving: int
    total_no_move: int
    total_nmpz: int
    wins: int
    losses: int
    mean_duration_secs: int
    last_rating: int
    max_rating: int
    max_rating_time: str

    def __str__(self):
        return ("\n  ".join([
            f"Total Games: {self.total_games}",
            f"  Moving: {self.total_moving}",
            f"  No Move: {self.total_no_move}",
            f"  NMPZ: {self.total_nmpz}",
            f"Wins: {self.wins}",
            f"Losses: {self.losses}",
            f"Mean Duration (secs): {self.mean_duration_secs}",
            f"Last Rating: {self.last_rating}",
            f"Max Rating: {self.max_rating} at {self.max_rating_time}"
        ]))

    @classmethod
    def from_games(cls, games: list[GeoguessrDuelGame]) -> 'RankedDuelsSummary':
        """
        Create a RankedDuelsSummary instance from a list of duel games.
        """
        if not games:
            return cls(0, 0, 0, 0, 0, 0, 0, 0, 0, "")
        
        total_games = len(games)
        total_moving = sum(1 for game in games if game.mode == GameMode.MOVING)
        total_no_move = sum(1 for game in games if game.mode == GameMode.NO_MOVE)
        total_nmpz = sum(1 for game in games if game.mode == GameMode.NMPZ)
        wins = sum(1 for game in games if game.won)
        losses = total_games - wins
        total_duration = sum(game.duration_secs for game in games)
        mean_duration_secs = total_duration // total_games
        
        # Handle games with null ratings gracefully
        games_with_ratings = [g for g in games if g.rating_after is not None]
        if games_with_ratings:
            last_rating = games_with_ratings[0].rating_after
            max_rating_game = max(games_with_ratings, key=lambda g: g.rating_after)
            max_rating = max_rating_game.rating_after
            max_rating_time = max_rating_game.start_time
        else:
            last_rating = 0
            max_rating = 0
            max_rating_time = ""

        return cls(
            total_games=total_games,
            total_moving=total_moving,
            total_no_move=total_no_move,
            total_nmpz=total_nmpz,
            wins=wins,
            losses=losses,
            mean_duration_secs=mean_duration_secs,
            last_rating=last_rating,
            max_rating=max_rating,
            max_rating_time=max_rating_time
        )


class PlayerData:
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
        # Ensure the output directory exists (create if missing) so callers can write into it
        os.makedirs(dirpath, exist_ok=True)

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

    def last_challenge_seed(self) -> str:
        """
        Return the challenge_token of the most recent daily challenge game, or empty string if none
        """
        if not self.daily_challenge_games:
            return ""
        # Assuming games are in chronological order, return the latest
        return self.daily_challenge_games[0].challenge_token
    
    def last_ranked_duel_id(self) -> str:
        """
        Return the game_id of the most recent ranked duel game, or empty string if none
        """
        if not self.ranked_duel_games:
            return ""
        return self.ranked_duel_games[0].game_id
    
    def last_team_duel_id(self) -> str:
        """
        Return the game_id of the most recent ranked team duel game, or empty string if none
        """
        last_id = ""
        last_time = None
        for game_list in self.ranked_team_duel_games.values():
            if game_list:
                id = game_list[0].game_id
                time = game_list[0].start_time
                if not last_time or time > last_time:
                    last_id = id
                    last_time = time
        return last_id
    
    def get_country_rounds(self, teammate: str|None = None, mode: GameMode|None = None) -> dict[str: list[GeoguessrDuelRound]]:
        """
        Get a dictionary mapping country codes in uppercase to lists of duel rounds played in those countries.

        """
        rounds_by_country: dict[str: list[GeoguessrDuelRound]] = {}
        duel_games = self.ranked_duel_games
        if teammate:
            duel_games = self.ranked_team_duel_games.get(teammate, [])
        if mode:
            duel_games = [game for game in duel_games if game.mode == mode]
        for game in duel_games:
            for round in game.rounds:
                country_code = round.country_code.upper()
                if country_code not in rounds_by_country:
                    rounds_by_country[country_code] = []
                rounds_by_country[country_code].append(round)
        return rounds_by_country
        


if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Print player data summary")
    parser.add_argument("player", help="Player name or ID to filter by")
    parser.add_argument("-t", "--teammate", help="Optional teammate name", default=None)
    parser.add_argument("-c", "--country", help="Optional country code or name", default=None)
    parser.add_argument("-m", "--game-mode", help="Game mode", choices=[mode.value for mode in GameMode], default=None)

    args = parser.parse_args()
    
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
        sys.exit(0)
    
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
