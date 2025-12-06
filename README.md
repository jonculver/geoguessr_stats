# GeoGuessr Stats Collector

This tool collects and analyzes game data from GeoGuessr for a specified user. It fetches game history, including daily challenges, ranked duels, and team duels, and saves the results to a JSON file for further analysis.

## Features
- Fetches game data for a user from GeoGuessr
- Supports daily challenges, ranked duels, and team duels
- Progress bars for long-running data collection steps
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

Run the tool to collect data:
```bash
python main.py <username> --max-games <number>
```
- `<username>`: The username as listed in `users.json`
- `--max-games <number>`: (Optional) Maximum number of games to fetch (default: 50)

### Output
Results are saved in the `output` folder as `<username>_games.json`.

## Example
```bash
python main.py Draig --max-games 100
```
This will fetch up to 100 games for the user `Draig` and save the results in the `output/` folder

## Notes
- Ensure your GeoGuessr token is valid and up to date in `users.json`.
- The tool uses progress bars to indicate data fetching and processing steps.
- For best results, use a dedicated virtual environment.

