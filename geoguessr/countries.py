import json
from dataclasses import dataclass
from geoguessr.game import GeoguessrDuelRound

country_code_map = None

@dataclass
class CountryStats:
    country_code: str
    name: str
    total_rounds: int
    rounds_won: int
    win_percentage: int
    rounds_guessed_first: int
    total_damage_dealt: int
    total_damage_taken: int
    mean_distance: int
    mean_time: int
    mean_time_guessed_first: int
    mean_time_guessed_second: int

    @classmethod
    def from_rounds(cls, country_code: str, rounds: list[GeoguessrDuelRound]) -> 'CountryStats':
        """
        Create a CountryStats instance from a list of duel rounds.
        """
        rounds_won = sum(1 for round in rounds if round.damage_dealt > 0)
        win_percentage = (rounds_won * 100) // len(rounds) if rounds else 0
        rounds_guessed_first = sum(1 for round in rounds if round.guessed_first)
        total_damage_dealt = sum(round.damage_dealt for round in rounds)
        total_damage_taken = sum(round.damage_taken for round in rounds)
        mean_distance = sum(round.distance_meters for round in rounds) // len(rounds) if rounds else 0
        mean_time = sum(round.time_secs for round in rounds) // len(rounds) if rounds else 0
        mean_time_guessed_first = sum(round.time_secs for round in rounds if round.guessed_first) // rounds_guessed_first if rounds_guessed_first else 0
        mean_time_guessed_second = sum(round.time_secs for round in rounds if not round.guessed_first) // (len(rounds) - rounds_guessed_first) if (len(rounds) - rounds_guessed_first) else 0
        return cls(
            country_code=country_code,
            name=country_code_to_name(country_code),
            total_rounds=len(rounds),
            rounds_won=rounds_won,
            win_percentage=win_percentage,
            rounds_guessed_first=rounds_guessed_first,
            total_damage_dealt=total_damage_dealt,
            total_damage_taken=total_damage_taken,
            mean_distance=mean_distance,
            mean_time=mean_time,
            mean_time_guessed_first=mean_time_guessed_first,
            mean_time_guessed_second=mean_time_guessed_second
        )
        

def country_code_to_name(country_code: str) -> str:
    """
    Convert a country code to its full country name.
    Loads the mapping from countries.json on first use.
    """
    global country_code_map
    if country_code_map is None:
        with open("data/countries.json", "r", encoding="utf-8") as f:
            country_code_map = json.load(f)
    return country_code_map.get(country_code.upper(), "Unknown Country")

def name_to_country_code(name: str) -> str:
    """
    Convert a country name to its country code.
    Loads the mapping from countries.json on first use.
    """
    global country_code_map
    if country_code_map is None:
        with open("data/countries.json", "r", encoding="utf-8") as f:
            country_code_map = json.load(f)
    for code, country_name in country_code_map.items():
        if country_name.lower() == name.lower():
            return code
    return "Unknown"
