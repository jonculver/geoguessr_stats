from dataclasses import dataclass

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
        
    def _get_rounds(self, data: dict) -> list[GeoguessrDuelRound]:
        rounds = []