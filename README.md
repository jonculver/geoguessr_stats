# GeoGuessr Stats Collector

This tool collects and analyzes game data from GeoGuessr for a specified user. It fetches game history, including daily challenges, ranked duels, and team duels, and saves the results to JSON files for further analysis.

## Features
- Fetches game data for a user from GeoGuessr
- Supports daily challenges, ranked duels, unranked duels, and team duels
- Progress bars for long-running data collection steps
- Displays player statistics and summaries
- Outputs results to an organized JSON file in the `output` directory

## Installation

### 1. Create and activate a Python virtual environment
```bash
# Python 3.9+ recommended
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows (PowerShell)
# .venv\Scripts\Activate
```

### 2. Install required packages from requirements.txt
```bash
pip install -r requirements.txt
```

## User Tokens

Create a `users.json` file at the root of this repository with the following structure:

{
    "Username1": "Token1",
    "Username2": "Token2",
}

For every user to collect stats for find their token as follows:

### Chrome

1. Make sure they have logged in to Geoguessr in this browser
2. Have them visit ph`
3. Open DevTools and go to **Application** (sometimes called **Storage**)
4. In the left sidebar, go to **Storage** → **Cookies** → `https://www.geoguessr.com`
5. Find the cookie named `_ncfa` and copy its value into `users.json`

## Usage

The tool provides a command-line interface with multiple subcommands:

### Fetch Game Data

Collect game data for a user:
```bash
python -m geoguessr fetch <username> [--max-games <number>] [--overwrite]
```
- `<username>`: The username as listed in `users.json`
- `--max-games <number>`: (Optional) Maximum number of games to fetch (default: 1000)
- `--overwrite`: (Optional) Overwrite existing data files instead of appending

**Example:**
```bash
python -m geoguessr fetch Draig --max-games 100
```

### Display Player Statistics

Show statistics and summaries for a player:
```bash
python -m geoguessr display <player> [-t <teammate>] [-c <country>] [-m <game-mode>]
```
- `<player>`: Player name to display stats for
- `-t, --teammate <name>`: (Optional) Show stats for team duels with a specific teammate
- `-c, --country <code>`: (Optional) Show stats for a specific country (2-letter code or full name)
- `-m, --game-mode <mode>`: (Optional) Filter by game mode: `Moving`, `NoMove`, or `NMPZ`

**Examples:**
```bash
# Show overall ranked duel summary
python -m geoguessr display Draig

# Show team duel summary with a teammate
python -m geoguessr display Draig -t Juliette

# Show country-specific stats
python -m geoguessr display Draig -c US

# Show stats filtered by game mode
python -m geoguessr display Draig -m Moving
```

### Output
Results are saved in the `output` folder:
- `<username>_daily_challenge.json`: Daily challenge games
- `<username>_standard_games.json`: Standard (non-duel) games
- `<username>_ranked_duels.json`: Solo ranked duel games
- `<username>_unranked_duels.json`: Unranked (casual) duel games
- `<username>_<teammate>_ranked_team_duels.json`: Team duel games with each teammate

Duel round entries include additional location detail:
- `pano_id`: the Street View panorama id for the round
- `guess_locations`: a map of `playerId -> {lat, lng, country_code?}` for each player's guess on that round

Duel round entries also include multiplier ("multi") information:
- `round_multiplier` / `round_damage_multiplier`: the round-level multipliers from the duel payload
- `team_multiplier` / `opponent_multiplier`: per-team multipliers for that round
- `team_active_multiplier` / `opponent_active_multiplier`: whether the multiplier was active for each team

If your `output/*_duels.json` files were generated before multiplier fields were added, they will load with defaults (`1.0` / `False`). In that case, re-run `fetch` with `--overwrite` to backfill multipliers.

### Country (Per-round listing)

List duel rounds where the *actual* round country matches a given 2-letter code. Output includes the net damage, whether your guess was the correct country (when available), and useful URLs.

```bash
python -m geoguessr country <username> <country-code> [--include <ranked|unranked|both>] [--mode <moving|nm|nmpz>] [--max-games <n>]
```

- `<username>`: The username as listed in `users.json`
- `<country-code>`: 2-letter country code (e.g. `US`, `IT`)
- `--include`: (Optional) Which duels to include (`ranked`, `unranked`, or `both`)
- `--mode`: (Optional) Game mode filter (`moving`, `nm`, `nmpz`)
- `--max-games`: (Optional) Limit to rounds from the most recent N duel games

Output format (per round):
- `YYYY-MM-DD net=<int> round=<n> correct=<Y|N|?>`
- GeoGuessr duel URL
- Google Street View URL (if available)

Notes:
- `net` is multiplier-normalized: `(damage_taken / opponent_multiplier) - (damage_dealt / team_multiplier)`.
- `correct=Y/N` is based on `guess_locations[<your playerId>].country_code` if present; otherwise `correct=?`.
- Rounds are printed in chronological order (earliest → latest).

**Example:**
```bash
python -m geoguessr country Juliette IT
```

### Analyse Player Data

Analyse saved data for a player:
```bash
python -m geoguessr analyse <username> [--type <region|wrong-country>] [--mode <moving|nm|nmpz>] [--include <ranked|unranked|both>] [--max-games <n>] [--min-rounds <n>]
```

Options:
- `--type region`: Country-level analysis, restricted to rounds where **both players guessed the correct country**.
- `--type wrong-country`: For each actual country, print the percentage of rounds where you guessed the **wrong** country.
- `--mode`: Game mode filter (`moving`, `nm`, `nmpz`).
- `--include`: Which duels to include (`ranked`, `unranked`, or `both`).
- `--max-games`: Limit analysis to the most recent N games.
- `--min-rounds`: Only include countries with at least this many rounds.

If `--type` is omitted, the command lists countries sorted by **average net damage per round**, where:

$$\text{net} = \text{damage\_taken} - \text{damage\_dealt}$$

In duels, damage can be affected by multipliers ("multis"). The `analyse` command normalizes net damage by these multipliers:

$$\text{net} = \frac{\text{damage\_taken}}{\text{opponent\_multiplier}} - \frac{\text{damage\_dealt}}{\text{team\_multiplier}}$$

**Examples:**
```bash
# Default analysis (average net damage per country)
python -m geoguessr analyse Juliette

# Region-style analysis, No Move only, ranked only
python -m geoguessr analyse Juliette --type region --mode nm --include ranked

# Wrong-country percentage, using only the most recent 200 games
python -m geoguessr analyse Juliette --type wrong-country --max-games 200
```

Note: You need to run `fetch` first to populate the `output/` JSON files.

## Backward Compatibility

For backward compatibility, you can still use the old command format:
```bash
python main.py fetch <username> --max-games <number>
```

## Notes
- Ensure your GeoGuessr token is valid and up to date in `users.json`.
- The tool uses progress bars to indicate data fetching and processing steps.
- For best results, use a dedicated virtual environment.

