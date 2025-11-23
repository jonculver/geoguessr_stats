from dataclasses import dataclass
from datetime import datetime

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
    damage_dealt: int
    damage_taken: int

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
        self.player_id = player_id
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
        """
        Build a list of GeoguessrDuelRound from raw game JSON.

        For each round we return the panorama country code, the elapsed
        seconds for the round (end - timerStartTime), the player's
        distance in metres (rounded to int), the player's score (int)
        and the damage dealt by the player's team for that round (int).
        """

        def parse_iso(ts: str) -> datetime | None:
            if not ts:
                return None
            try:
                return datetime.fromisoformat(ts)
            except Exception:
                return None

        def to_int(value) -> int:
            try:
                return int(round(float(value)))
            except Exception:
                return 0

        # locate the player's object and their team
        player_obj = None
        player_team = None
        pid = getattr(self, 'player_id', None)
        for team in data.get('teams', []):
            for player in team.get('players', []):
                if player.get('playerId') == pid or player.get('id') == pid:
                    player_obj = player
                    player_team = team
                    break
            if player_obj:
                break

        # build lookups
        player_guesses = {}
        if player_obj:
            for g in player_obj.get('guesses', []):
                player_guesses[g.get('roundNumber')] = g

        team_round_results = {}
        opponent_round_results = {}
        if player_team:
            for rr in player_team.get('roundResults', []):
                team_round_results[rr.get('roundNumber')] = rr
        # find opponent team (first team with different id)
        opp_team = None
        for team in data.get('teams', []):
            if player_team and team.get('id') != player_team.get('id'):
                opp_team = team
                break
        if opp_team:
            for rr in opp_team.get('roundResults', []):
                opponent_round_results[rr.get('roundNumber')] = rr

        out: list[GeoguessrDuelRound] = []
        for r in data.get('rounds', []):
            rn = r.get('roundNumber')
            pano = r.get('panorama', {})
            country_code = pano.get('countryCode', '')

            timer_start = parse_iso(r.get('startTime'))
            end_time = parse_iso(r.get('endTime'))
            if timer_start and end_time:
                secs = (end_time - timer_start).total_seconds()
                time_secs = to_int(secs)
            else:
                time_secs = to_int(data.get('options', {}).get('roundTime', 0))

            guess = player_guesses.get(rn, {})
            distance_meters = to_int(guess.get('distance', 0))
            score = to_int(guess.get('score', 0))

            rr = team_round_results.get(rn)
            opp_rr = opponent_round_results.get(rn)
            damage_dealt = to_int(rr.get('damageDealt', 0)) if rr else 0
            damage_taken = to_int(opp_rr.get('damageDealt', 0)) if opp_rr else 0

            out.append(GeoguessrDuelRound(country_code=country_code,
                                          time_secs=time_secs,
                                          distance_meters=distance_meters,
                                          score=score,
                                          damage_dealt=damage_dealt,
                                          damage_taken=damage_taken))

        return out