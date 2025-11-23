# Wrapper around Geoguessr API Endpoints

import requests
import json
from dataclasses import dataclass

BASE_URL = "https://www.geoguessr.com/api"
_nfca_TOKEN = "qbL8x7iQNKQt4dB%2Bv6u8Tlda8CnYFpy32E7SrYiZc%2BY%3DYkrawXljhWiTu3djEW%2FNvnZ%2FK8SPp31jSBq%2BvVYWI55hssg%2Ff7GfbVJ7Nmyu2bmOHvi8aq9s3IEA6gwUOnukyWzOWZ9OXDCVOqcIwGX8Sos%3D"

# Display

ENDPOINTS = {
    "profile": "v3/profiles"
}

session = requests.Session()
session.cookies.set("_nfca", _nfca_TOKEN, domain="www.geoguessr.com")

profile = session.get(f"{BASE_URL}/{ENDPOINTS['profile']}")

@dataclass()
class GameType:
    RANKED_DUELS: str = "Duels"
    RANKED_TEAM_DUELS: str = "TeamDuels"
    DAILY_CHALLENGE: str = "DailyChallenge"
    UNKNOWN: str = "Unknown"

@dataclass()
class GameMode:
    MOVING: str = "Moving"
    NO_MOVE: str = "NoMove"
    NMPZ: str = "NMPZ"

@dataclass()
class GeoguessrChallengeGame:
    game_type: GameType
    game_id: str
    challenge_token: str
    points: int

@dataclass()
class GeoguessrDuelRound:
    country_code: str
    time_secs: int
    distance_meters: int
    score: int
    damage: int

@dataclass()
class GeoguessrDuelGame:
    game_type: GameType
    game_id: str
    mode: GameMode
    map: str
    rounds: list[GeoguessrDuelRound]
    rating_before: int
    rating_after: int
    game_mode_rating_before: int
    game_mode_rating_after: int

    def __init__(self, game_type: GameType, game_id: str, player_id: str, data: dict) -> None:
        self.game_type = game_type
        self.game_id = game_id
        self.mode = self._get_mode(data)
        self.map = data.get('options', {}).get('map', "").get('name', "")
        self.rounds = len(data.get('rounds', []))

        for team in data.get('teams', []):
            for player in team.get('players', []):
                if player.get('id') == player_id:
                    self.rounds = data.get('rounds', 0)
                    self.rating_before = player.get('ratingBefore', 0)
                    self.rating_after = player.get('ratingAfter', 0)
                    self.game_mode_rating_before = player.get('gameModeRatingBefore', 0)
                    self.game_mode_rating_after = player.get('gameModeRatingAfter', 0)
        return

    
    def _get_mode(self, data) -> GameMode:
        options = data.get('options', {})
        movement_options = options.get('movementOptions', {})
        forbid_moving = movement_options.get('forbidMoving', False)
        forbid_zooming = movement_options.get('forbidZooming', False)
        if not forbid_moving:
            return GameMode.MOVING
        elif forbid_zooming:
            return GameMode.NMPZ
        else:
            return GameMode.NO_MOVE
    
    def 
    
    @staticmethod
    def from_game_data(data: dict) -> 'GeoguessrGame':
        game_id = data.get('gameId', "")
        game_mode = GeoguessrDuelGame._get_mode(data)

        competitive_mode = data.get('competitiveGameMode', "")
        if "isDailyChallenge" in data:
            return GeoguessrGame(GameType.DAILY_CHALLENGE, 
                                 game_id,
                                 points=data.get('points', 0),
                                 challenge_token=data.get('challengeToken', ''))
        
        if game_mode == "Duels" and competitive_mode == "StandardDuels":
            return GeoguessrGame(GameType.RANKED_DUELS, game_id)
        elif game_mode == "TeamDuels" and competitive_mode == "StandardTeamDuels":
            return GeoguessrGame(GameType.RANKED_TEAM_DUELS, game_id)
        return GeoguessrGame(GameType.UNKNOWN, game_id)


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
    
    def _query_game_data(self, game_id: str) -> GeoguessrGame:
        url = f"https://game-server.geoguessr.com/api/duels/{game_id}"
        raw_data = self._make_request(url)
        return self._payload_to_game(raw_data)
    
    def _payload_to_game(self, payload: dict) -> GeoguessrGame:
        game_id = payload.get('gameId')
        if not game_id:
            return None
        if "isDailyChallenge" in payload:
            return GeoguessrGame(GameType.DAILY_CHALLENGE, 
                                 game_id,
                                 points=payload.get('points', 0),
                                 challenge_token=payload.get('challengeToken', ''))
        
        game_mode = payload.get('gameMode', "")
        competitive_mode = payload.get('competitiveGameMode', "")
        if game_mode == "Duels" and competitive_mode == "StandardDuels":
            return GeoguessrGame(GameType.RANKED_DUELS, game_id)
        elif game_mode == "TeamDuels" and competitive_mode == "StandardTeamDuels":
            return GeoguessrGame(GameType.RANKED_TEAM_DUELS, game_id)
        return None
    
    def _get_game_ids_page(self, pagination_token) -> tuple[GeoguessrGame, str]:
        url = f"https://www.geoguessr.com/api/v4/feed/private?paginationToken={pagination_token}"
        raw_data = self._make_request(url)
        games = []
        entries = raw_data['entries']
        token = raw_data.get('paginationToken')
        for item in entries:
            data = json.loads(item['payload'])
            for activity in data:
                if isinstance(activity, dict):
                    game_data = activity.get('payload', {})
                    game = self._payload_to_game(game_data)
                    if game:
                        games.append(game)
        return games, token
    
    def get_games(self, max_games=1000) -> list:
        game_ids = []
        token = ""
        while len(game_ids) < max_games and token:
            ids, token = self._get_game_ids_page(token)
            game_ids.extend(ids)
            #print(f"Fetched {len(game_ids)} game IDs so far. Next token: {token}")
        return game_ids[:max_games]

    
geo = Geoguessr("Draig", _nfca_TOKEN)

print(len(geo.get_game_ids(1)))

#print(geo.get_elo())