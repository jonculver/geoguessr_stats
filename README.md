# GeoGuessr Stats Collector

This tool collects and analyzes game data from GeoGuessr for a specified user. It fetches game history, including daily challenges, ranked duels, and team duels, and saves the results to JSON files for further analysis.

## Features
- Fetches game data for a user from GeoGuessr
- Supports daily challenges, ranked duels, and team duels
- Progress bars for long-running data collection steps
- Displays player statistics and summaries
- Outputs results to an organized JSON file in the `output` directory

## Installation

### 1. Create and activate a Python virtual environment
```bash
python -m venv .venv
.venv\Scripts\Activate
```

### 2. Install required packages from requirements.txt
```bash
pip install -r requirements.txt
```

## User Tokens

Create a `users.json` file at the root of this repsoitory with the following structure:

{
    "Username1": "Token1",
    "Username2": "Token2",
}

For every user to collect stats for find their token as follows:

### Chrome

1. Make sure they have logged in to Geoguessr in this browser
2. Have them vist `https://www.geoguessr.com/api/v3/profiles`
3. Inspect the page and go to the network tab
4. Refresh the page. Under Headers -> Set Cookie, look for
    ```_ncfa=<token>```
5. Copy the token into `users.json`

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
- `<username>_ranked_duels.json`: Solo ranked duel games
- `<username>_<teammate>_ranked_team_duels.json`: Team duel games with each teammate

## Backward Compatibility

For backward compatibility, you can still use the old command format:
```bash
python main.py fetch <username> --max-games <number>
```

## Notes
- Ensure your GeoGuessr token is valid and up to date in `users.json`.
- The tool uses progress bars to indicate data fetching and processing steps.
- For best results, use a dedicated virtual environment.

