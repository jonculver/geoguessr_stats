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
        # @@@ TODO: Implement this
        return cls(
            country_code=country_code,
            name=country_code_to_name(country_code),
            total_rounds=len(rounds),
            rounds_won=0,
            rounds_guessed_first=0,
            total_damage_dealt=0,
            total_damage_taken=0,
            mean_distance=0,
            mean_time=0,
            mean_time_guessed_first=0,
            mean_time_guessed_second=0
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
