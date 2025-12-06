# Wrapper around Geoguessr API Endpoints

import requests
import json
from tqdm import tqdm
from dataclasses import fields
from geoguessr.game import GeoguessrDuelGame, GeoguessrChallengeGame, GameType

class Geoguessr:
    def __init__(self, username: str, ncfa_cookie: str, max_games=50) -> None:
        self.username = username
        self.ncfa_cookie = ncfa_cookie
        self.user_id = self._get_userID()
        self.userids_to_usernames = {}
        self.daily_challenge_games = []
        self.ranked_duel_games = []
        self.ranked_team_duel_games = {}

        print(f"Fetching games for user '{self.username}' (ID: {self.user_id})")
        self._get_games(max_games=max_games)
        print("Converting user IDs to usernames...")
        self._convert_ids_to_usernames()
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
    
    def _query_game_data(self, game_type: str, game_id: str) -> GeoguessrDuelGame | None:
        url = f"https://game-server.geoguessr.com/api/duels/{game_id}"
        raw_data = self._make_request(url)
        if raw_data is None:
            return None
        return GeoguessrDuelGame(game_type, game_id, self.user_id, raw_data)
    
    def _get_game_type(self, payload: dict) -> GameType:
        if "isDailyChallenge" in payload:
            return GameType.DAILY_CHALLENGE
        game_id = payload.get('gameId')
        if not game_id:
            return GameType.UNKNOWN       
        game_mode = payload.get('gameMode', "")
        competitive_mode = payload.get('competitiveGameMode', "")
        if game_mode == "Duels" and competitive_mode == "StandardDuels":
            return GameType.RANKED_DUELS
        elif game_mode == "TeamDuels" and competitive_mode == "StandardDuels":
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
        elif game_type != GameType.UNKNOWN:
            game_id = game_data.get('gameId', "")
            games_dict[game_type].append(game_id)

    def _get_game_ids_page(self, pagination_token) -> tuple[dict, str]:
        """
        Return a dictionary containing a list of games for each game type and the next pagination token
        """
        url = f"https://www.geoguessr.com/api/v4/feed/private?paginationToken={pagination_token}"
        raw_data = self._make_request(url)
        games = {GameType.DAILY_CHALLENGE: [], GameType.RANKED_DUELS: [], GameType.RANKED_TEAM_DUELS: []}
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
    
    def _convert_ids_to_usernames(self):
        """
        For each game in ranked duel and team duels, convert user IDs to usernames
        """
        # Combine all games for a single progress bar
        all_games = list(self.ranked_duel_games)
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

    def _get_games(self, max_games=1000):
        """
        Return a dictionary containing a list of games for each game type
        """
        games = {GameType.DAILY_CHALLENGE: [], GameType.RANKED_DUELS: [], GameType.RANKED_TEAM_DUELS: []}
        token = ""
        total_game_ids = 0
        # Use tqdm to show progress of fetching game IDs
        with tqdm(total=max_games, desc="Fetching game IDs") as pbar:
            while total_game_ids < max_games and token is not None:
                temp_games, token = self._get_game_ids_page(token)
                for type in games.keys():
                    prev_count = len(games[type])
                    games[type].extend(temp_games[type])
                    # Update progress bar by the number of new games added
                    pbar.update(len(games[type]) - prev_count)
                total_game_ids = sum(len(games[type]) for type in games.keys())
        
        self.daily_challenge_games = games[GameType.DAILY_CHALLENGE]

        # For each duel game query the game data. Use a progress bar for this slow step
        for type in [GameType.RANKED_DUELS, GameType.RANKED_TEAM_DUELS]:
            duel_game_ids = games[type]
            duel_games = []
            for game_id in tqdm(duel_game_ids, desc=f"Querying {type} data"):
                duel_game = self._query_game_data(type, game_id)
                if duel_game is not None:
                    duel_games.append(duel_game)
            games[type] = duel_games

        self.ranked_duel_games = games[GameType.RANKED_DUELS]

        # For team duels, group by teammate
        team_duel_dict = {}
        for game in games[GameType.RANKED_TEAM_DUELS]:
            teammate = self._get_username(game.teammate)
            game.teamate = teammate
            safename = self._username_to_filename(teammate)

            if safename not in team_duel_dict:
                team_duel_dict[safename] = []
            team_duel_dict[safename].append(game)

        self.ranked_team_duel_games = team_duel_dict

    