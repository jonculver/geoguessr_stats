# Wrapper around Geoguessr API Endpoints

import requests
import json

from dataclasses import fields
from geoguessr.game import GeoguessrDuelGame, GeoguessrChallengeGame, GameType

class Geoguessr:
    def __init__(self, username: str, ncfa_cookie: str) -> None:
        self.username = username
        self.ncfa_cookie = ncfa_cookie
        self.user_id = self._get_userID()
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
            data = json.loads(item['payload'])
            for activity in data:
                if isinstance(activity, dict):
                    game_data = activity.get('payload', {})
                    game_id = game_data.get('gameId', "")
                    time = activity.get('time', "")
                    game_type = self._get_game_type(game_data)
                    if game_type == GameType.DAILY_CHALLENGE:
                        challenge_token = game_data.get('challengeToken', "")
                        points = game_data.get('points', 0)
                        game = GeoguessrChallengeGame(game_type, time, challenge_token, points)
                        games[GameType.DAILY_CHALLENGE].append(game)
                    elif game_type != GameType.UNKNOWN:
                        games[game_type].append(game_id)
        return games, token
    
    def get_games(self, max_games=1000) -> dict:
        """
        Return a dictionary containing a list of games for each game type
        """
        games = {GameType.DAILY_CHALLENGE: [], GameType.RANKED_DUELS: [], GameType.RANKED_TEAM_DUELS: []}
        token = ""
        total_game_ids = 0
        while total_game_ids < max_games and token is not None:
            temp_games, token = self._get_game_ids_page(token)
            for type in games.keys():
                games[type].extend(temp_games[type])
            total_game_ids = sum(len(games[type]) for type in games.keys())
            print(f"Fetched {total_game_ids} game IDs so far. Next token: {token}")

        # For each duel game query the game data
        for type in [GameType.RANKED_DUELS, GameType.RANKED_TEAM_DUELS]:
            duel_game_ids = games[type]
            duel_games = []
            for game_id in duel_game_ids:
                duel_game = self._query_game_data(type, game_id)
                if duel_game is not None:
                    duel_games.append(duel_game)
            games[type] = duel_games

        return games

    