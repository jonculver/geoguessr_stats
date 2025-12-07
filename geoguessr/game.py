from dataclasses import dataclass
from datetime import datetime
from enum import Enum

class GameType(str, Enum):
    RANKED_DUELS = "Duels"
    RANKED_TEAM_DUELS = "TeamDuels"
    DAILY_CHALLENGE = "DailyChallenge"
    UNKNOWN = "Unknown"

class GameMode(str, Enum):
    MOVING = "Moving"
    NO_MOVE = "NoMove"
    NMPZ = "NMPZ"

@dataclass()
class GeoguessrChallengeGame:
    game_type: GameType
    time: str
    challenge_token: str
    points: int

@dataclass()
class GeoguessrDuelRound:
    country_code: str
    start_time: str
    time_secs: int
    distance_meters: int
    score: int
    damage_dealt: int
    damage_taken: int
    guessed_first: bool

@dataclass()
class GeoguessrDuelGame:
    game_type: GameType
    game_id: str
    time: str
    mode: GameMode
    map: str
    rounds: list[GeoguessrDuelRound]
    opponents: list[str]
    opponent_rating: int = 0
    rating_before: int = 0
    rating_after: int = 0
    game_mode_rating_before: int = 0
    game_mode_rating_after: int = 0
    teammate: str = ""
    start_time: str = ""
    duration_secs: int = 0

    @classmethod
    def from_json(cls, data: dict) -> 'GeoguessrDuelGame':
        """Create a GeoguessrDuelGame instance from a JSON object."""

        game_type_str = data.get('game_type', 'Unknown')
        # Convert string to GameType enum
        try:
            game_type = GameType(game_type_str)
        except ValueError:
            game_type = GameType.UNKNOWN
        
        mode_str = data.get('mode', 'Unknown')
        # Convert string to GameMode enum
        try:
            mode = GameMode(mode_str)
        except ValueError:
            mode = GameMode.MOVING
        
        game_start_time = data.get('start_time', '')
        
        # Parse rounds
        rounds = []
        for round_data in data.get('rounds', []):
            rounds.append(GeoguessrDuelRound(
                country_code=round_data.get('country_code', ''),
                start_time=round_data.get('start_time', game_start_time),
                time_secs=round_data.get('time_secs', 0),
                distance_meters=round_data.get('distance_meters', 0),
                score=round_data.get('score', 0),
                damage_dealt=round_data.get('damage_dealt', 0),
                damage_taken=round_data.get('damage_taken', 0),
                guessed_first=round_data.get('guessed_first', False)
            ))
        
        instance = cls(
            game_type=game_type,
            game_id=data.get('game_id', ''),
            time=data.get('start_time', ''),
            mode=mode,
            map=data.get('map', ''),
            rounds=rounds,
            opponents=data.get('opponents', []),
            opponent_rating=data.get('opponent_rating', 0),
            rating_before=data.get('rating_before', 0),
            rating_after=data.get('rating_after', 0),
            game_mode_rating_before=data.get('game_mode_rating_before', 0),
            game_mode_rating_after=data.get('game_mode_rating_after', 0),
            teammate=data.get('teammate', ''),
            start_time=data.get('start_time', ''),
            duration_secs=data.get('duration_secs', 0)
        )
        instance.player_id = data.get('player_id', '')
        return instance

    @classmethod
    def from_geoguessr_data(cls, game_type: GameType, game_id: str, player_id: str, data: dict) -> 'GeoguessrDuelGame':
        instance = cls(
            game_type=game_type,
            game_id=game_id,
            time="",
            mode=GeoguessrDuelGame._get_mode(data),
            map="",
            rounds=[],
            opponents=[]
        )
        instance.player_id = player_id
        
        map_dict = data.get('options', {}).get('map', {})
        if map_dict:
            instance.map = map_dict.get('name', "")
        else:
            instance.map = ""
        instance.rounds, instance.start_time, instance.duration_secs = instance._get_rounds(data)

        for team in data.get('teams', []):
            home_team = False
            players = []
            rating = 0
            for player in team.get('players', []):
                progress = player.get('progressChange', {})
                rating_progress = progress.get('rankedSystemProgress', {})
                team_rating = progress.get('rankedTeamDuelsProgress', {})
                if player.get('playerId') != player_id:
                    # Record who we are playing with or against
                    players.append(player.get('playerId', ""))
                    # For teammates or opponents just record the maximum rating before
                    player_rating = 0
                    if rating_progress:
                        player_rating = rating_progress.get('ratingBefore', 0)
                    elif team_rating:
                        player_rating = team_rating.get('ratingBefore', 0)
                    if player_rating:
                        rating = max(rating, player_rating)            
                else:
                    # For us record all the stats we have
                    home_team = True
                    if rating_progress:
                        instance.rating_before = rating_progress.get('ratingBefore', 0)
                        instance.rating_after = rating_progress.get('ratingAfter', 0)
                        instance.game_mode_rating_before = rating_progress.get('gameModeRatingBefore', 0)
                        instance.game_mode_rating_after = rating_progress.get('gameModeRatingAfter', 0)
                    elif team_rating:
                        instance.rating_before = team_rating.get('ratingBefore', 0)
                        instance.rating_after = team_rating.get('ratingAfter', 0)

            if home_team and len(players) == 1:
                instance.teammate = players[0]
            elif not home_team:
                instance.opponents = players
                instance.opponent_rating = rating
        return instance

    
    @staticmethod
    def _get_mode(data) -> GameMode:
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
        
    def _get_rounds(self, data: dict) -> tuple[list[GeoguessrDuelRound], str, int]:
        """
        Build a list of GeoguessrDuelRound from raw game JSON.

        For each round we return the panorama country code, the elapsed
        seconds for the round (end - timerStartTime), the player's
        distance in metres (rounded to int), the player's score (int)
        and the damage dealt by the player's team for that round (int).

        Also return the start time for the first round and the time from
        the start of the first round to the end of the last round in seconds.
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

        start_time: str = ""
        start_time_iso: datetime | None = None
        end_time_iso: datetime | None = None

        out: list[GeoguessrDuelRound] = []
        for r in data.get('rounds', []):
            rn = r.get('roundNumber')
            pano = r.get('panorama', {})
            country_code = pano.get('countryCode', '')

            round_start_time = r.get('startTime', "")
            timer_start = parse_iso(round_start_time)
            if not start_time_iso:
                start_time_iso = timer_start
                start_time = round_start_time
            end_time = parse_iso(r.get('endTime'))
            end_time_iso = end_time
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

            # determine which team guessed first by comparing the earliest
            # guess timestamps for this round among all players on each team.
            def earliest_guess_time(team_obj) -> datetime | None:
                if not team_obj:
                    return None
                earliest = None
                for p in team_obj.get('players', []):
                    for g in p.get('guesses', []):
                        if g.get('roundNumber') != rn:
                            continue
                        t = parse_iso(g.get('created'))
                        if not t:
                            continue
                        if earliest is None or t < earliest:
                            earliest = t
                return earliest

            team_earliest = earliest_guess_time(player_team)
            opp_earliest = earliest_guess_time(opp_team)
            if team_earliest and opp_earliest:
                guessed_first = team_earliest < opp_earliest
            elif team_earliest and not opp_earliest:
                guessed_first = True
            else:
                guessed_first = False

            out.append(GeoguessrDuelRound(country_code=country_code,
                                          start_time=round_start_time,
                                          time_secs=time_secs,
                                          distance_meters=distance_meters,
                                          score=score,
                                          damage_dealt=damage_dealt,
                                          damage_taken=damage_taken,
                                          guessed_first=guessed_first))
            
        # Calculate total elapsed time
        total_elapsed_secs = 0
        if start_time_iso and end_time_iso:
            total_elapsed_secs = int((end_time_iso - start_time_iso).total_seconds())

        return out, start_time, total_elapsed_secs