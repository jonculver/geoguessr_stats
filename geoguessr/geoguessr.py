# Wrapper around Geoguessr API Endpoints

import requests
import json
from tqdm import tqdm
from dataclasses import fields
from typing import Optional
from geoguessr.user import PlayerData
from geoguessr.game import GeoguessrChallengeGame, GeoguessrDuelGame, GeoguessrStandardGame, GameType

USERNAME_MAP_FILE = "output/username_map.json"

class Geoguessr:
    def __init__(
        self,
        username: str,
        ncfa_cookie: str,
        last_challenge_seed: str,
        last_standard_game_token: str,
        last_ranked_duel_id: str,
        last_unranked_duel_id: str,
        last_team_duel_id: str,
        max_games: int = 50,
    ) -> None:
        self.username = username
        self.ncfa_cookie = ncfa_cookie
        self.user_id = self._get_userID()
        self.userids_to_usernames = {}
        self.daily_challenge_games = []
        self.standard_games = []
        self.ranked_duel_games = []
        self.unranked_duel_games = []
        self.ranked_team_duel_games = {}

        print(
            f"Fetching games for user '{self.username}' (ID: {self.user_id}) since last challenge seed '{last_challenge_seed}', "
            f"last standard game token '{last_standard_game_token}', "
            f"last ranked duel ID '{last_ranked_duel_id}', last unranked duel ID '{last_unranked_duel_id}', "
            f"and last team duel ID '{last_team_duel_id}'..."
        )
        self._get_games(last_challenge_seed=last_challenge_seed,
                        last_standard_game_token=last_standard_game_token,
                        last_ranked_duel_id=last_ranked_duel_id,
                        last_unranked_duel_id=last_unranked_duel_id,
                        last_team_duel_id=last_team_duel_id,
                        max_games=max_games)
        print("Converting user IDs to usernames...")
        self._load_username_map()
        self._convert_ids_to_usernames()
        self._save_username_map()
        return

    def _make_request(self, endpoint) -> None:
        response = requests.request("GET", endpoint, headers=self._get_headers())
        if response.ok:
            return response.json()
        return response.ok

    def _get_headers(self) -> dict:
        cookie = self.ncfa_cookie
        if cookie is None:
            raise KeyError("Please define GEOGUESSR_COOKIE as an environment variable")
        return {
            "authority": "www.geoguessr.com",
            "accept": "*/*",
            "accept-language": "en-US,en;q=0.9",
            "content-type": "application/json",
            "cookie": "_ncfa="+cookie,
            "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.5005.99 Safari/537.36",
        }
    
    def _get_userID(self) -> str:
        url = "https://www.geoguessr.com/api/v3/profiles"
        raw_data = self._make_request(url)
        user = raw_data.get('user', {})
        return user.get('id', "")        
    
    def _query_game_data(self, game_type: str, game_id: str) -> Optional[GeoguessrDuelGame]:
        url = f"https://game-server.geoguessr.com/api/duels/{game_id}"
        raw_data = self._make_request(url)
        if raw_data is None:
            return None
        return GeoguessrDuelGame.from_geoguessr_data(game_type, game_id, self.user_id, raw_data)

    def _query_standard_game_data(self, entry: dict) -> Optional[GeoguessrStandardGame]:
        game_token = entry.get("game_token", "")
        if not game_token:
            return None
        url = f"https://www.geoguessr.com/api/v3/games/{game_token}"
        raw_data = self._make_request(url)
        if raw_data is None or not isinstance(raw_data, dict):
            return None
        return GeoguessrStandardGame(
            game_type=GameType.STANDARD,
            time=entry.get("time", ""),
            game_token=game_token,
            map=raw_data.get("map", ""),
            map_name=raw_data.get("mapName", ""),
            mode=raw_data.get("mode", ""),
            state=raw_data.get("state", ""),
            round_count=raw_data.get("roundCount", 0) or 0,
            raw=raw_data,
        )
    
    def _get_game_type(self, payload: dict) -> GameType:
        if "isDailyChallenge" in payload:
            return GameType.DAILY_CHALLENGE
        game_mode = payload.get('gameMode', "")
        if game_mode == "Standard":
            return GameType.STANDARD
        game_id = payload.get('gameId')
        if not game_id:
            return GameType.UNKNOWN       
        competitive_modes = ["StandardDuels", "NoMoveDuels", "NmpzDuels"]
        competitive_mode = payload.get('competitiveGameMode', "")
        if game_mode == "Duels":
            if competitive_mode in competitive_modes:
                return GameType.RANKED_DUELS
            # Non-competitive duels are treated as unranked.
            return GameType.UNRANKED_DUELS
        elif game_mode == "TeamDuels" and competitive_mode in competitive_modes:
            return GameType.RANKED_TEAM_DUELS
        return GameType.UNKNOWN

    def _extract_game_data(self, games_dict, time, game_data: dict):
        """ Given a dictionary of games and raw game data, extract the relevant game information """
        game_type = self._get_game_type(game_data)
        if game_type == GameType.DAILY_CHALLENGE:
            challenge_token = game_data.get('challengeToken', "")
            time = time
            points = game_data.get('points', 0)
            game = GeoguessrChallengeGame(game_type, time, challenge_token, points)
            games_dict[GameType.DAILY_CHALLENGE].append(game)
        elif game_type == GameType.STANDARD:
            game_token = game_data.get("gameToken", "")
            if game_token:
                games_dict[GameType.STANDARD].append(
                    {
                        "game_token": game_token,
                        "time": time,
                        "map_slug": game_data.get("mapSlug", ""),
                        "map_name": game_data.get("mapName", game_data.get("mapname", "")),
                        "points": game_data.get("points", 0),
                    }
                )
        elif game_type != GameType.UNKNOWN:
            game_id = game_data.get('gameId', "")
            games_dict[game_type].append(game_id)

    def _get_game_ids_page(self, pagination_token) -> tuple[dict, str]:
        """
        Return a dictionary containing a list of games for each game type and the next pagination token
        """
        url = f"https://www.geoguessr.com/api/v4/feed/private?paginationToken={pagination_token}"
        raw_data = self._make_request(url)
        games = {
            GameType.DAILY_CHALLENGE: [],
            GameType.STANDARD: [],
            GameType.RANKED_DUELS: [],
            GameType.UNRANKED_DUELS: [],
            GameType.RANKED_TEAM_DUELS: [],
        }
        entries = raw_data['entries']
        token = raw_data.get('paginationToken')
        for item in entries:
            time = item.get('time', "")
            data = json.loads(item['payload'])
            if isinstance(data, dict):
                # A single instance where _this_ is the payload
                self._extract_game_data(games, time, data)
            elif isinstance(data, list):
                # A list of several instances, each with their own time and payload
                for activity in data:
                    if isinstance(activity, dict):
                        time = activity.get('time', "")
                        payload = activity.get('payload', {})
                        self._extract_game_data(games, time, payload)
        return games, token
    
    def _get_username(self, user_id: str) -> str:
        """
        Given a user ID, return the corresponding username
        """
        if user_id in self.userids_to_usernames:
            return self.userids_to_usernames[user_id]
        
        url = f"https://www.geoguessr.com/api/v3/users/{user_id}"
        raw_data = self._make_request(url)
        username = user_id
        if isinstance(raw_data, dict):
            username = raw_data.get('nick', user_id)
        self.userids_to_usernames[user_id] = username
        return username
    
    def _load_username_map(self):
        """
        Load the username map from the JSON file if it exists
        """
        try:
            with open(USERNAME_MAP_FILE, "r", encoding="utf-8") as f:
                self.userids_to_usernames = json.load(f)
        except FileNotFoundError:
            self.userids_to_usernames = {}

    def _save_username_map(self):
        """
        Save the username map to the JSON file
        """
        with open(USERNAME_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(self.userids_to_usernames, f, indent=2)
    
    def _convert_ids_to_usernames(self):
        """
        For each game in ranked duel and team duels, convert user IDs to usernames
        """
        # Combine all games for a single progress bar
        all_games = list(self.ranked_duel_games)
        all_games.extend(self.unranked_duel_games)
        for games in self.ranked_team_duel_games.values():
            all_games.extend(games)
        from tqdm import tqdm
        for game in tqdm(all_games, desc="Converting user IDs to usernames"):
            game.opponents = [self._get_username(uid) for uid in game.opponents]
    
    def _username_to_filename(self, username: str) -> str:
        """
        Convert a username to a safe filename by replacing spaces with underscores
        and restricting to alphanumeric characters and underscores
        """
        safe_username = username.replace(" ", "_")
        safe_username = "".join(c for c in safe_username if c.isalnum() or c == "_")
        return safe_username

    def _get_games(self, last_challenge_seed, last_standard_game_token, last_ranked_duel_id, last_unranked_duel_id, last_team_duel_id, max_games=1000):
        """
        Return a dictionary containing a list of games for each game type since the last seen IDs
        """
        games = {
            GameType.DAILY_CHALLENGE: [],
            GameType.STANDARD: [],
            GameType.RANKED_DUELS: [],
            GameType.UNRANKED_DUELS: [],
            GameType.RANKED_TEAM_DUELS: [],
        }
        # Track which game types have found their last game
        complete_types = {
            GameType.DAILY_CHALLENGE: False,
            GameType.STANDARD: False,
            GameType.RANKED_DUELS: False,
            GameType.UNRANKED_DUELS: False,
            GameType.RANKED_TEAM_DUELS: False,
        }
        token = ""
        total_game_ids = 0
        # Use tqdm to show progress of fetching game IDs
        while total_game_ids < max_games and token is not None:
            temp_games, token = self._get_game_ids_page(token)
            
            for game_type in games.keys():
                # Skip if we've already found the last game for this type
                if complete_types[game_type]:
                    continue
                    
                for game in temp_games[game_type]:
                    # Check if this is the last game we already have
                    if game_type == GameType.DAILY_CHALLENGE:
                        if game.challenge_token == last_challenge_seed:
                            complete_types[game_type] = True
                            break
                    elif game_type == GameType.STANDARD:
                        if (game.get("game_token", "") if isinstance(game, dict) else "") == last_standard_game_token:
                            complete_types[game_type] = True
                            break
                    elif game_type == GameType.RANKED_DUELS:
                        if game == last_ranked_duel_id:
                            complete_types[game_type] = True
                            break
                    elif game_type == GameType.UNRANKED_DUELS:
                        if game == last_unranked_duel_id:
                            complete_types[game_type] = True
                            break
                    elif game_type == GameType.RANKED_TEAM_DUELS:
                        if game == last_team_duel_id:
                            complete_types[game_type] = True
                            break
                    
                    # Add the game and increment counter
                    games[game_type].append(game)
                    total_game_ids += 1
                    
                    # Check if we've hit the max games limit
                    if total_game_ids >= max_games:
                        complete_types[game_type] = True
                        break
            
            # Stop if all game types are complete
            if all(complete_types.values()):
                break
        
        print(
            f"Found {len(games[GameType.DAILY_CHALLENGE])} new daily challenge games, "
            f"{len(games[GameType.STANDARD])} new standard games, "
            f"{len(games[GameType.RANKED_DUELS])} new ranked duel games, "
            f"{len(games[GameType.UNRANKED_DUELS])} new unranked duel games, "
            f"and {len(games[GameType.RANKED_TEAM_DUELS])} new ranked team duel games. "
        )
        self.daily_challenge_games = games[GameType.DAILY_CHALLENGE]

        # Query standard game details.
        self.standard_games = []
        standard_entries = games[GameType.STANDARD]
        queried_standard = []
        for entry in tqdm(standard_entries, desc="Querying Standard game data"):
            if not isinstance(entry, dict):
                continue
            game_data = self._query_standard_game_data(entry)
            if game_data is not None:
                queried_standard.append(game_data)
        self.standard_games = queried_standard

        # Query duel game details (ranked, unranked, and team duels).
        self.ranked_duel_games = []
        self.unranked_duel_games = []
        self.ranked_team_duel_games = {}

        for game_type in [GameType.RANKED_DUELS, GameType.UNRANKED_DUELS, GameType.RANKED_TEAM_DUELS]:
            game_ids = games[game_type]
            queried_games = []
            for game_id in tqdm(game_ids, desc=f"Querying {game_type} data"):
                game_data = self._query_game_data(game_type, game_id)
                if game_data is not None:
                    queried_games.append(game_data)

            if game_type == GameType.RANKED_DUELS:
                self.ranked_duel_games = queried_games
            elif game_type == GameType.UNRANKED_DUELS:
                self.unranked_duel_games = queried_games
            elif game_type == GameType.RANKED_TEAM_DUELS:
                # Group team duels by teammate (safe username) and store teammate as username.
                for game in queried_games:
                    teammate_id = game.teammate
                    teammate_username = self._get_username(teammate_id)
                    game.teammate = teammate_username
                    safename = self._username_to_filename(teammate_username)
                    if safename not in self.ranked_team_duel_games:
                        self.ranked_team_duel_games[safename] = []
                    self.ranked_team_duel_games[safename].append(game)

    