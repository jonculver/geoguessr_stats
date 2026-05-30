from __future__ import annotations

import io
import json
import os
import re
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal, Optional
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from geoguessr.__main__ import analyse_command, country_command, fetch_command
from geoguessr.game import GameMode
from geoguessr.countries import country_code_to_name
from geoguessr.user import PlayerData

try:
    import reverse_geocoder as _rg
except Exception:  # pragma: no cover
    _rg = None


TEAM_DUEL_PARTNER_MIN_GAMES = int(os.getenv("GG_TEAM_DUEL_MIN_GAMES", "10"))
CLASSIC_MAP_MIN_GAMES = int(os.getenv("GG_CLASSIC_MAP_MIN_GAMES", "50"))


def _parse_iso_datetime(ts: str) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    s = ts.strip()
    if not s:
        return None
    try:
        s = s.replace("Z", "+00:00")
        # Best-effort: trim excessive fractional seconds.
        m = re.match(r"^(.*T\d\d:\d\d:\d\d)\.(\d+)([+-]\d\d:\d\d)$", s)
        if m:
            base, frac, offset = m.group(1), m.group(2), m.group(3)
            frac = (frac[:6]).ljust(6, "0")
            s = f"{base}.{frac}{offset}"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


def _classic_mode_label(raw: dict) -> str:
    forbid_moving = bool(raw.get("forbidMoving", False))
    forbid_zooming = bool(raw.get("forbidZooming", False))
    if not forbid_moving:
        return "moving"
    return "nmpz" if forbid_zooming else "nm"


def _classic_maps_for_user(username: str, min_games: int = CLASSIC_MAP_MIN_GAMES) -> list[str]:
    username = (username or "").strip()
    if not username:
        return []
    if min_games < 1:
        min_games = 1
    player_data = PlayerData(username)
    counts: dict[str, int] = {}
    for g in getattr(player_data, "standard_games", []) or []:
        name = (getattr(g, "map_name", "") or "").strip()
        if name:
            counts[name] = counts.get(name, 0) + 1

    maps = [name for name, n in counts.items() if n >= min_games]
    return sorted(maps, key=lambda s: s.lower())


def _classic_country_rows(
    username: str,
    mode: Optional[str],
    map_name: Optional[str],
    max_games: Optional[int],
    max_days: Optional[int],
    min_rounds: Optional[int],
    sort_by: str,
) -> list[dict[str, object]]:
    username = (username or "").strip()
    if not username:
        return []

    mode_norm = (mode or "").strip().lower() or None
    map_norm = (map_name or "").strip() or None
    if map_norm == "any":
        map_norm = None

    player_data = PlayerData(username)
    games = list(getattr(player_data, "standard_games", []) or [])

    # Prefer newest first.
    games.sort(key=lambda g: (_parse_iso_datetime(getattr(g, "time", "") or "") or datetime.min.replace(tzinfo=timezone.utc)), reverse=True)

    if max_days is not None:
        if max_days <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
        games = [g for g in games if (_parse_iso_datetime(getattr(g, "time", "") or "") or datetime.min.replace(tzinfo=timezone.utc)) >= cutoff]

    if max_games is not None:
        if max_games <= 0:
            return []
        games = games[:max_games]

    if min_rounds is not None and min_rounds <= 0:
        return []

    # country_code -> stats
    stats: dict[str, dict[str, float]] = {}

    # Cache reverse geocodes to keep things snappy.
    geo_cache: dict[tuple[float, float], str] = {}

    def guess_cc(lat: object, lng: object) -> str:
        if _rg is None:
            return ""
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            return ""
        key = (round(lat_f, 5), round(lng_f, 5))
        if key in geo_cache:
            return geo_cache[key]
        try:
            res = _rg.search((lat_f, lng_f), mode=1)
            cc = ""
            if isinstance(res, list) and res and isinstance(res[0], dict):
                cc = str(res[0].get("cc") or "").upper()
            geo_cache[key] = cc
            return cc
        except Exception:
            geo_cache[key] = ""
            return ""

    for g in games:
        raw = getattr(g, "raw", {}) or {}
        if not isinstance(raw, dict):
            continue
        if (raw.get("state") or getattr(g, "state", "")) != "finished":
            continue

        if mode_norm:
            if _classic_mode_label(raw) != mode_norm:
                continue

        if map_norm:
            gn = (raw.get("mapName") or getattr(g, "map_name", "") or "").strip()
            if gn != map_norm:
                continue

        rounds = raw.get("rounds")
        guesses = raw.get("guesses")
        if not isinstance(guesses, list):
            player = raw.get("player")
            if isinstance(player, dict):
                guesses = player.get("guesses")

        if not isinstance(rounds, list) or not isinstance(guesses, list):
            continue
        n = min(len(rounds), len(guesses))
        for i in range(n):
            r = rounds[i]
            gu = guesses[i]
            if not isinstance(r, dict) or not isinstance(gu, dict):
                continue

            correct = str(r.get("streakLocationCode") or "").upper()
            if not correct:
                continue

            g_cc = guess_cc(gu.get("lat"), gu.get("lng"))
            is_correct = 1.0 if (g_cc and g_cc == correct) else 0.0

            score = 0.0
            try:
                score = float(gu.get("roundScoreInPoints") or 0)
            except Exception:
                score = 0.0

            s = stats.setdefault(correct, {"rounds": 0.0, "correct": 0.0, "score": 0.0})
            s["rounds"] += 1.0
            s["correct"] += is_correct
            s["score"] += score

    rows: list[dict[str, object]] = []
    for cc, s in stats.items():
        rounds = int(s.get("rounds", 0.0) or 0.0)
        if rounds <= 0:
            continue
        if min_rounds is not None and rounds < min_rounds:
            continue
        correct = int(s.get("correct", 0.0) or 0.0)
        score_sum = float(s.get("score", 0.0) or 0.0)
        acc = (100.0 * correct / rounds) if rounds else 0.0
        avg_score = (score_sum / rounds) if rounds else 0.0
        rows.append(
            {
                "cc": cc,
                "name": country_code_to_name(cc) or cc,
                "rounds": rounds,
                "correct": correct,
                "accuracy": acc,
                "avg_score": avg_score,
            }
        )

    sort_norm = (sort_by or "").strip().lower()
    if sort_norm == "avg_score":
        # Lowest average score first (ascending).
        rows.sort(key=lambda r: (float(r.get("avg_score", 0.0) or 0.0), int(r.get("rounds", 0) or 0)))
    else:
        # Least accurate first (ascending).
        rows.sort(key=lambda r: (float(r.get("accuracy", 0.0) or 0.0), int(r.get("rounds", 0) or 0)))
    return rows


def _classic_country_options_for_user(
    username: str,
    mode: Optional[str],
    map_name: Optional[str],
    max_games: Optional[int],
    max_days: Optional[int],
) -> list[dict[str, str]]:
    """Return available country options (panorama countries) for classic games under the given filters."""
    username = (username or "").strip()
    if not username:
        return []

    mode_norm = (mode or "").strip().lower() or None
    map_norm = (map_name or "").strip() or None
    if map_norm == "any":
        map_norm = None

    player_data = PlayerData(username)
    games = list(getattr(player_data, "standard_games", []) or [])
    games.sort(
        key=lambda g: (
            _parse_iso_datetime(getattr(g, "time", "") or "")
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )

    if max_days is not None:
        if max_days <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
        games = [
            g
            for g in games
            if (
                _parse_iso_datetime(getattr(g, "time", "") or "")
                or datetime.min.replace(tzinfo=timezone.utc)
            )
            >= cutoff
        ]

    if max_games is not None:
        if max_games <= 0:
            return []
        games = games[:max_games]

    ccs: set[str] = set()
    for g in games:
        raw = getattr(g, "raw", {}) or {}
        if not isinstance(raw, dict):
            continue
        if (raw.get("state") or getattr(g, "state", "")) != "finished":
            continue
        if mode_norm and _classic_mode_label(raw) != mode_norm:
            continue
        if map_norm:
            gn = (raw.get("mapName") or getattr(g, "map_name", "") or "").strip()
            if gn != map_norm:
                continue
        rounds = raw.get("rounds")
        if not isinstance(rounds, list):
            continue
        for r in rounds:
            if not isinstance(r, dict):
                continue
            cc = str(r.get("streakLocationCode") or "").upper()
            if cc:
                ccs.add(cc)

    out: list[dict[str, str]] = []
    for cc in sorted(ccs, key=lambda s: s.upper()):
        out.append({"cc": cc, "name": country_code_to_name(cc) or cc})
    return out


def _classic_country_round_rows(
    username: str,
    country: str,
    mode: Optional[str],
    map_name: Optional[str],
    max_games: Optional[int],
    max_days: Optional[int],
) -> list[dict[str, object]]:
    """Return per-round rows for classic games where the panorama country matches `country`."""
    username = (username or "").strip()
    if not username:
        return []

    target_cc = (country or "").strip().upper()
    if not target_cc or len(target_cc) != 2:
        return []

    mode_norm = (mode or "").strip().lower() or None
    map_norm = (map_name or "").strip() or None
    if map_norm == "any":
        map_norm = None

    player_data = PlayerData(username)
    games = list(getattr(player_data, "standard_games", []) or [])
    games.sort(
        key=lambda g: (
            _parse_iso_datetime(getattr(g, "time", "") or "")
            or datetime.min.replace(tzinfo=timezone.utc)
        ),
        reverse=True,
    )

    if max_days is not None:
        if max_days <= 0:
            return []
        cutoff = datetime.now(timezone.utc) - timedelta(days=max_days)
        games = [
            g
            for g in games
            if (
                _parse_iso_datetime(getattr(g, "time", "") or "")
                or datetime.min.replace(tzinfo=timezone.utc)
            )
            >= cutoff
        ]

    if max_games is not None:
        if max_games <= 0:
            return []
        games = games[:max_games]

    geo_cache: dict[tuple[float, float], str] = {}

    def decode_pano_id(pano_id: str) -> str:
        """Decode stored pano_id.

        Our JSON often stores pano IDs hex-encoded; decode to UTF-8 when it looks like hex.
        """
        if not pano_id:
            return ""
        s = pano_id.strip()
        if len(s) % 2 != 0:
            return s
        try:
            int(s, 16)
        except Exception:
            return s
        try:
            return bytes.fromhex(s).decode("utf-8")
        except Exception:
            return s

    def streetview_url(pano_id: object, lat: object, lng: object) -> str:
        try:
            pano = decode_pano_id(str(pano_id or ""))
        except Exception:
            pano = ""
        if pano:
            return f"https://www.google.com/maps/@?api=1&map_action=pano&pano={pano}"
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            return ""
        return f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={lat_f},{lng_f}"

    def guess_cc(lat: object, lng: object) -> str:
        if _rg is None:
            return ""
        try:
            lat_f = float(lat)
            lng_f = float(lng)
        except Exception:
            return ""
        key = (round(lat_f, 5), round(lng_f, 5))
        if key in geo_cache:
            return geo_cache[key]
        try:
            res = _rg.search((lat_f, lng_f), mode=1)
            cc = ""
            if isinstance(res, list) and res and isinstance(res[0], dict):
                cc = str(res[0].get("cc") or "").upper()
            geo_cache[key] = cc
            return cc
        except Exception:
            geo_cache[key] = ""
            return ""

    rows: list[dict[str, object]] = []
    for g in games:
        raw = getattr(g, "raw", {}) or {}
        if not isinstance(raw, dict):
            continue
        if (raw.get("state") or getattr(g, "state", "")) != "finished":
            continue

        if mode_norm and _classic_mode_label(raw) != mode_norm:
            continue

        if map_norm:
            gn = (raw.get("mapName") or getattr(g, "map_name", "") or "").strip()
            if gn != map_norm:
                continue

        rounds = raw.get("rounds")
        guesses = raw.get("guesses")
        if not isinstance(guesses, list):
            player = raw.get("player")
            if isinstance(player, dict):
                guesses = player.get("guesses")

        if not isinstance(rounds, list) or not isinstance(guesses, list):
            continue
        n = min(len(rounds), len(guesses))

        dt = _parse_iso_datetime(getattr(g, "time", "") or "")
        date = dt.date().isoformat() if dt else ""
        mode_label = _classic_mode_label(raw)
        token = (getattr(g, "game_token", "") or "").strip()
        game_url = f"https://www.geoguessr.com/game/{token}" if token else ""

        ts = dt.timestamp() if dt else float("-inf")

        for i in range(n):
            r = rounds[i]
            gu = guesses[i]
            if not isinstance(r, dict) or not isinstance(gu, dict):
                continue
            correct = str(r.get("streakLocationCode") or "").upper()
            if correct != target_cc:
                continue

            sv_url = streetview_url(r.get("panoId"), r.get("lat"), r.get("lng"))

            g_cc = guess_cc(gu.get("lat"), gu.get("lng"))
            if not g_cc:
                correct_flag = "?"
            else:
                correct_flag = "Y" if g_cc == correct else "N"

            score: Optional[float]
            try:
                raw_score = gu.get("roundScoreInPoints")
                if raw_score is None:
                    raw_score = gu.get("score")
                score = float(raw_score) if raw_score is not None else None
            except Exception:
                score = None

            distance_km = None
            dist_m = gu.get("distanceInMeters")
            if dist_m is None:
                dist_m = gu.get("distance")
            try:
                if dist_m is not None:
                    distance_km = float(dist_m) / 1000.0
            except Exception:
                distance_km = None

            rows.append(
                {
                    "date": date,
                    "mode": mode_label,
                    "score": score,
                    "correct": correct_flag,
                    "distance_km": distance_km,
                    "round": i + 1,
                    "game_url": game_url,
                    "sv_url": sv_url,
                    "_ts": ts,
                }
            )

    # Lowest score first; unknown scores last.
    def sort_key(r: dict[str, object]):
        sc = r.get("score")
        try:
            score_val = float(sc) if sc is not None else float("inf")
        except Exception:
            score_val = float("inf")
        try:
            ts_val = float(r.get("_ts") or float("-inf"))
        except Exception:
            ts_val = float("-inf")
        try:
            round_val = int(r.get("round") or 0)
        except Exception:
            round_val = 0
        return (score_val, ts_val, round_val)

    rows.sort(key=sort_key)
    for r in rows:
        r.pop("_ts", None)
    return rows


def _classic_country_links_url(
    username: str,
    country: str,
    mode: Optional[str],
    map_name: Optional[str],
    max_games: Optional[int],
    max_days: Optional[int],
) -> str:
    params: dict[str, object] = {"username": username, "country": country}
    if mode:
        params["mode"] = mode
    if map_name:
        params["map_name"] = map_name
    if max_games is not None:
        params["max_games"] = max_games
    if max_days is not None:
        params["max_days"] = max_days
    return f"/classic-country?{urlencode(params)}"


def _load_usernames(repo_root: Path) -> list[str]:
    try:
        users_path = repo_root / "users.json"
        raw = json.loads(users_path.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return sorted([str(k) for k in raw.keys()])
    except Exception:
        pass
    return []


def _run_command_capture(func, args_obj) -> tuple[str, str]:
    stdout_buf = io.StringIO()
    stderr_buf = io.StringIO()
    with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
        try:
            func(args_obj)
        except SystemExit:
            # CLI commands use sys.exit() for validation; in the web UI we want
            # to show captured output instead of returning a 500.
            pass
    return stdout_buf.getvalue(), stderr_buf.getvalue()


def _run_command_capture_in_dir(func, args_obj, cwd: Path) -> tuple[str, str]:
    prev = os.getcwd()
    try:
        os.chdir(str(cwd))
        return _run_command_capture(func, args_obj)
    finally:
        try:
            os.chdir(prev)
        except Exception:
            pass


def _wants_json(request: Request) -> bool:
    accept = (request.headers.get("accept") or "").lower()
    return "application/json" in accept


def _team_duel_teammates_for_user(repo_root: Path, username: str) -> list[str]:
    output_dir = repo_root / "output"
    if not username or not output_dir.exists():
        return []
    pattern = re.compile(rf"^{re.escape(username)}_(?P<teammate>.+)_ranked_team_duels\.json$")
    teammates: set[str] = set()
    for p in output_dir.glob(f"{username}_*_ranked_team_duels.json"):
        m = pattern.match(p.name)
        if not m:
            continue
        teammate = (m.group("teammate") or "").strip()
        if not teammate:
            continue

        max_mode_count = 0
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            games = raw
            if isinstance(raw, dict) and isinstance(raw.get("games"), list):
                games = raw.get("games")

            if isinstance(games, list):
                mode_counts: dict[str, int] = {}
                for g in games:
                    if not isinstance(g, dict):
                        continue
                    mode = str(g.get("mode") or "").strip().lower()
                    if not mode:
                        continue
                    mode_counts[mode] = mode_counts.get(mode, 0) + 1
                max_mode_count = max(mode_counts.values(), default=0)
        except Exception:
            max_mode_count = 0

        if max_mode_count >= TEAM_DUEL_PARTNER_MIN_GAMES:
            teammates.add(teammate)
    return sorted(teammates, key=lambda s: s.lower())


def _parse_mode(mode: Optional[str]) -> Optional[GameMode]:
    if not mode:
        return None
    mode_norm = mode.strip().lower()
    if mode_norm == "moving":
        return GameMode.MOVING
    if mode_norm in {"nm", "no_move", "nomove"}:
        return GameMode.NO_MOVE
    if mode_norm == "nmpz":
        return GameMode.NMPZ
    return None


def _available_games_count(username: str, include: str, mode: Optional[str], max_days: Optional[int]) -> int:
    if not username:
        return 0
    player_data = PlayerData(username)

    if isinstance(include, str) and include.startswith("team:"):
        teammate = include.split(":", 1)[1].strip()
        team_map = getattr(player_data, "ranked_team_duel_games", {}) or {}
        games = list(team_map.get(teammate, []))
    elif include == "ranked":
        games = list(getattr(player_data, "ranked_duel_games", []) or [])
    elif include == "unranked":
        games = list(getattr(player_data, "unranked_duel_games", []) or [])
    elif include == "party":
        games = list(getattr(player_data, "party_duel_games", []) or [])
    else:
        games = list(getattr(player_data, "ranked_duel_games", []) or []) + list(
            getattr(player_data, "unranked_duel_games", []) or []
        )

    gm = _parse_mode(mode)
    if gm is not None:
        games = [g for g in games if getattr(g, "mode", None) == gm]


    if max_days is not None:
        if max_days <= 0:
            return 0

        from datetime import datetime, timezone

        def _parse_ts(ts: str) -> float:
            if not ts:
                return float("-inf")
            try:
                import re

                s = ts.replace("Z", "+00:00")
                m = re.match(r"^(.*T\d\d:\d\d:\d\d)\.(\d+)([+-]\d\d:\d\d)$", s)
                if m:
                    base, frac, offset = m.group(1), m.group(2), m.group(3)
                    frac = (frac[:6]).ljust(6, "0")
                    s = f"{base}.{frac}{offset}"
                return datetime.fromisoformat(s).timestamp()
            except Exception:
                return float("-inf")

        cutoff = datetime.now(timezone.utc).timestamp() - (float(max_days) * 86400.0)

        def game_ts(g) -> float:
            return _parse_ts(getattr(g, "start_time", "") or getattr(g, "time", "") or "")

        games = [g for g in games if game_ts(g) >= cutoff]
    return len(games)


_ANALYSE_ROW_RE = re.compile(
    r"^\s*(?P<idx>\d+)\s+(?P<cc>[A-Z?]{2})\s+(?P<name>.*?):\s+avg_net=(?P<avg>[-0-9.]+)\s+rounds=(?P<rounds>\d+)\s+win%=(?P<win>[-0-9.]+)\s*$"
)

_WRONG_COUNTRY_ROW_RE = re.compile(
    r"^\s*(?P<idx>\d+)\s+(?P<cc>[A-Z?]{2})\s+(?P<name>.*?):\s+wrong%=(?P<wrong_pct>[-0-9.]+)\s+wrong=(?P<wrong>\d+)\s+rounds=(?P<rounds>\d+)\s*$"
)

_COUNTRY_LINE_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?:duel=(?P<duel>\S+)\s+)?(?:mode=(?P<mode>\S+)\s+)?net=(?P<net>-?\d+)\s+round=(?P<round>\d+)\s+correct=(?P<correct>[YN?])(?:\s+dist_km=(?P<dist_km>[-0-9.]+))?\s*$"
)


def _parse_analyse(stdout_text: str, analysis_type: Optional[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in stdout_text.splitlines():
        if analysis_type == "wrong-country":
            m = _WRONG_COUNTRY_ROW_RE.match(line)
            if not m:
                continue
            rows.append(
                {
                    "idx": int(m.group("idx")),
                    "cc": m.group("cc"),
                    "name": m.group("name"),
                    "wrong_pct": float(m.group("wrong_pct")),
                    "wrong": int(m.group("wrong")),
                    "rounds": int(m.group("rounds")),
                }
            )
        else:
            m = _ANALYSE_ROW_RE.match(line)
            if not m:
                continue
            rows.append(
                {
                    "idx": int(m.group("idx")),
                    "cc": m.group("cc"),
                    "name": m.group("name"),
                    "avg_net": float(m.group("avg")),
                    "rounds": int(m.group("rounds")),
                    "win": float(m.group("win")),
                }
            )
    return rows


def _parse_country(stdout_text: str) -> list[dict[str, Any]]:
    lines = stdout_text.splitlines()
    i = 0
    out: list[dict[str, Any]] = []
    while i < len(lines):
        m = _COUNTRY_LINE_RE.match(lines[i])
        if not m:
            i += 1
            continue

        date = m.group("date")
        duel = m.group("duel") or "?"
        mode = m.group("mode") or "?"
        net = int(m.group("net"))
        round_n = int(m.group("round"))
        correct = m.group("correct")
        dist_km_raw = m.group("dist_km")
        distance_km = float(dist_km_raw) if dist_km_raw is not None else None

        duel_url = ""
        sv_url = ""
        if i + 1 < len(lines):
            duel_url = lines[i + 1].strip()
        if i + 2 < len(lines):
            sv_url = lines[i + 2].strip()

        out.append(
            {
                "date": date,
                "duel_type": f"{duel} {mode}",
                "net": net,
                "round": round_n,
                "correct": correct,
                "distance_km": distance_km,
                "duel_url": duel_url,
                "sv_url": sv_url,
            }
        )
        i += 3

    return out


def _country_options_for_user(
    username: str,
    include: str,
    mode: Optional[Literal["moving", "nm", "nmpz"]],
    max_games: Optional[int],
    max_days: Optional[int],
) -> list[dict[str, str]]:
    class Args:
        pass

    args = Args()
    args.username = username
    args.type = None
    args.mode = mode
    args.include = include
    args.max_games = max_games
    args.max_days = max_days
    args.min_rounds = 1

    stdout, _stderr = _run_command_capture(analyse_command, args)
    rows = _parse_analyse(stdout, None)
    out: list[dict[str, str]] = []
    for r in rows:
        cc = (r.get("cc") or "").upper()
        name = r.get("name") or ""
        if not cc:
            continue
        out.append({"cc": cc, "name": name})
    return out


def create_app() -> FastAPI:
    repo_root = Path(__file__).resolve().parents[2]
    templates = Jinja2Templates(directory=str(Path(__file__).resolve().parent / "templates"))

    app = FastAPI(title="GeoGuessr Stats")

    @app.get("/player-summary")
    def player_summary(username: str):
        """Lightweight counts for the Update Data tab."""
        username = (username or "").strip()
        if not username:
            return JSONResponse({"username": "", "rows": []})

        def date_only(ts: str) -> Optional[str]:
            if not ts:
                return None
            if "T" in ts:
                ts = ts.split("T", 1)[0]
            # Expect YYYY-MM-DD
            if len(ts) >= 10 and ts[0:4].isdigit() and ts[5:7].isdigit() and ts[8:10].isdigit():
                return ts[0:10]
            return None

        def mode_label(mode_value: object) -> str:
            if mode_value == GameMode.MOVING:
                return "Moving"
            if mode_value == GameMode.NO_MOVE:
                return "NM"
            if mode_value == GameMode.NMPZ:
                return "NMPZ"
            return "?"

        # label -> {count, min_date, max_date}
        buckets: dict[str, dict[str, object]] = {}

        def add_entry(label: str, ts: str) -> None:
            if not label:
                return
            b = buckets.setdefault(label, {"count": 0, "min": None, "max": None})
            b["count"] = int(b.get("count", 0) or 0) + 1
            d = date_only(ts)
            if not d:
                return
            cur_min = b.get("min")
            cur_max = b.get("max")
            if cur_min is None or d < cur_min:  # type: ignore[operator]
                b["min"] = d
            if cur_max is None or d > cur_max:  # type: ignore[operator]
                b["max"] = d

        def add_duel(kind: str, game, partner: Optional[str] = None) -> None:
            ml = mode_label(getattr(game, "mode", None))
            label = f"{kind} {ml}" if not partner else f"{kind} ({partner}) {ml}"
            ts = getattr(game, "start_time", "") or getattr(game, "time", "") or ""
            add_entry(label, ts)

        player_data = PlayerData(username)
        for g in getattr(player_data, "daily_challenge_games", []) or []:
            add_entry("Daily Challenge Games", getattr(g, "time", "") or "")
        for g in getattr(player_data, "standard_games", []) or []:
            add_entry("Classic Games", getattr(g, "time", "") or "")
        for g in getattr(player_data, "ranked_duel_games", []) or []:
            add_duel("Ranked", g)
        for g in getattr(player_data, "unranked_duel_games", []) or []:
            add_duel("Unranked", g)
        for g in getattr(player_data, "party_duel_games", []) or []:
            add_duel("Party", g)

        team_map = getattr(player_data, "ranked_team_duel_games", {}) or {}

        # Total team duels across all partners (no min-games threshold).
        for _partner, games_for_partner in team_map.items():
            for g in list(games_for_partner or []):
                ts = getattr(g, "start_time", "") or getattr(g, "time", "") or ""
                add_entry("Total Team Duels", ts)

        partners = []
        for partner in sorted([str(k) for k in team_map.keys()], key=lambda s: s.lower()):
            games_for_partner = list(team_map.get(partner, []) or [])
            if len(games_for_partner) >= TEAM_DUEL_PARTNER_MIN_GAMES:
                partners.append(partner)
                for g in games_for_partner:
                    add_duel("Team", g, partner=partner)

        order: list[str] = [
            "Ranked Moving",
            "Ranked NM",
            "Ranked NMPZ",
            "Unranked Moving",
            "Unranked NM",
            "Unranked NMPZ",
            "Party Moving",
            "Party NM",
            "Party NMPZ",
            "Total Team Duels",
        ]
        for partner in partners:
            order.extend(
                [
                    f"Team ({partner}) Moving",
                    f"Team ({partner}) NM",
                    f"Team ({partner}) NMPZ",
                ]
            )

        # Non-duel game types at the bottom.
        order.extend(["Classic Games", "Daily Challenge Games"])

        rows: list[dict[str, object]] = []
        for label in order:
            b = buckets.get(label)
            if not b:
                continue
            count = int(b.get("count", 0) or 0)
            if count <= 0:
                continue
            if label.startswith("Team (") and count < TEAM_DUEL_PARTNER_MIN_GAMES:
                continue
            rows.append(
                {
                    "label": label,
                    "count": count,
                    "from": b.get("min"),
                    "to": b.get("max"),
                }
            )

        # Include any unexpected labels (future-proofing) in stable order.
        for label in sorted([k for k in buckets.keys() if k not in set(order)], key=lambda s: s.lower()):
            b = buckets.get(label)
            if not b:
                continue
            count = int(b.get("count", 0) or 0)
            if count <= 0:
                continue
            if label.startswith("Team (") and count < TEAM_DUEL_PARTNER_MIN_GAMES:
                continue
            rows.append({"label": label, "count": count, "from": b.get("min"), "to": b.get("max")})

        return JSONResponse({"username": username, "rows": rows})

    @app.get("/team-duel-partners")
    def team_duel_partners(username: str):
        return {"partners": _team_duel_teammates_for_user(repo_root, username)}

    @app.get("/classic-maps")
    def classic_maps(username: str):
        return {"maps": _classic_maps_for_user(username)}

    @app.post("/classic", response_class=HTMLResponse)
    def run_classic(
        request: Request,
        username: str = Form(...),
        mode: Optional[Literal["moving", "nm", "nmpz"]] = Form(None),
        map_name: str = Form(""),
        max_games: Optional[int] = Form(None),
        max_days: Optional[int] = Form(None),
        min_rounds: Optional[int] = Form(None),
        sort_by: Optional[Literal["general", "accuracy", "avg_score"]] = Form("general"),
    ):
        rows: list[dict[str, object]] = []
        stderr = ""
        try:
            sort_norm = (sort_by or "").strip().lower() or "general"
            # Back-compat: old UI exposed score vs accuracy as separate analyses.
            if sort_norm == "general":
                sort_norm = "accuracy"
            rows = _classic_country_rows(username, mode, map_name, max_games, max_days, min_rounds, sort_norm)
            for r in rows:
                cc = str(r.get("cc") or "").strip().upper()
                if cc:
                    r["links_url"] = _classic_country_links_url(username, cc, mode, map_name, max_games, max_days)
        except Exception as e:
            stderr = str(e)

        # Keep other tabs consistent.
        analyse_available_games = _available_games_count(username, "both", None, None)
        country_available_games = analyse_available_games

        # Default classic-country form state (so the template always has something).
        classic_country_form = {
            "username": username,
            "country": "",
            "mode": None,
            "map_name": "",
            "max_games": None,
            "max_days": None,
        }

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "analyse": None,
                "analyse_available_games": analyse_available_games,
                "country": None,
                "classic": None,
                "classic_country": None,
                "classic_country_form": classic_country_form,
                "classic_country_options": (
                    _classic_country_options_for_user(username, None, "", None, None) if username else []
                ),
                "classic_form": {
                    "username": username,
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                    "min_rounds": None,
                    "sort_by": "general",
                },
                "classic_maps": _classic_maps_for_user(username) if username else [],
                "country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "include": "both",
                    "max_games": None,
                    "max_days": None,
                    "min_net": -5000,
                },
                "country_available_games": country_available_games,
                "country_options": (_country_options_for_user(username, "both", None, None, None) if username else []),
                "update": None,
                "update_form": {
                    "username": username,
                },
                "classic": {
                    "form": {
                        "username": username,
                        "mode": mode,
                        "map_name": map_name,
                        "max_games": max_games,
                        "max_days": max_days,
                        "min_rounds": min_rounds,
                        "sort_by": sort_by or "accuracy",
                    },
                    "stderr": stderr,
                    "rows": rows,
                    "maps": _classic_maps_for_user(username) if username else [],
                },
                "classic_form": {
                    "username": username,
                    "mode": mode,
                    "map_name": map_name,
                    "max_games": max_games,
                    "max_days": max_days,
                    "min_rounds": min_rounds,
                    "sort_by": sort_by or "accuracy",
                },
                "classic_maps": _classic_maps_for_user(username) if username else [],
            },
        )

    @app.post("/classic-country", response_class=HTMLResponse)
    def run_classic_country(
        request: Request,
        username: str = Form(...),
        country: str = Form(...),
        mode: Optional[Literal["moving", "nm", "nmpz"]] = Form(None),
        map_name: str = Form(""),
        max_games: Optional[int] = Form(None),
        max_days: Optional[int] = Form(None),
    ):
        rows: list[dict[str, object]] = []
        stderr = ""
        try:
            rows = _classic_country_round_rows(username, country, mode, map_name, max_games, max_days)
        except Exception as e:
            stderr = str(e)

        analyse_available_games = _available_games_count(username, "both", None, None)
        country_available_games = analyse_available_games

        classic_maps = _classic_maps_for_user(username) if username else []
        classic_country_options = (
            _classic_country_options_for_user(username, mode, map_name, max_games, max_days) if username else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "analyse": None,
                "analyse_available_games": analyse_available_games,
                "country": None,
                "country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "include": "both",
                    "max_games": None,
                    "max_days": None,
                    "min_net": -5000,
                },
                "country_available_games": country_available_games,
                "country_options": (_country_options_for_user(username, "both", None, None, None) if username else []),
                "classic": None,
                "classic_form": {
                    "username": username,
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                    "min_rounds": None,
                    "sort_by": "accuracy",
                },
                "classic_maps": classic_maps,
                "classic_country": {
                    "form": {
                        "username": username,
                        "country": country,
                        "mode": mode,
                        "map_name": map_name,
                        "max_games": max_games,
                        "max_days": max_days,
                    },
                    "stderr": stderr,
                    "rows": rows,
                    "maps": classic_maps,
                },
                "classic_country_form": {
                    "username": username,
                    "country": country,
                    "mode": mode,
                    "map_name": map_name,
                    "max_games": max_games,
                    "max_days": max_days,
                },
                "classic_country_options": classic_country_options,
                "update": None,
                "update_form": {
                    "username": username,
                },
            },
        )

    @app.get("/classic-country", response_class=HTMLResponse)
    def run_classic_country_get(
        request: Request,
        username: str,
        country: str,
        mode: Optional[Literal["moving", "nm", "nmpz"]] = None,
        map_name: str = "",
        max_games: Optional[int] = None,
        max_days: Optional[int] = None,
    ):
        rows: list[dict[str, object]] = []
        stderr = ""
        try:
            rows = _classic_country_round_rows(username, country, mode, map_name, max_games, max_days)
        except Exception as e:
            stderr = str(e)

        analyse_available_games = _available_games_count(username, "both", None, None)
        country_available_games = analyse_available_games

        classic_maps = _classic_maps_for_user(username) if username else []
        classic_country_options = (
            _classic_country_options_for_user(username, mode, map_name, max_games, max_days) if username else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "analyse": None,
                "analyse_available_games": analyse_available_games,
                "country": None,
                "country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "include": "both",
                    "max_games": None,
                    "max_days": None,
                    "min_net": -5000,
                },
                "country_available_games": country_available_games,
                "country_options": (
                    _country_options_for_user(username, "both", None, None, None) if username else []
                ),
                "classic": None,
                "classic_form": {
                    "username": username,
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                    "min_rounds": None,
                    "sort_by": "accuracy",
                },
                "classic_maps": classic_maps,
                "classic_country": {
                    "form": {
                        "username": username,
                        "country": country,
                        "mode": mode,
                        "map_name": map_name,
                        "max_games": max_games,
                        "max_days": max_days,
                    },
                    "stderr": stderr,
                    "rows": rows,
                    "maps": classic_maps,
                },
                "classic_country_form": {
                    "username": username,
                    "country": country,
                    "mode": mode,
                    "map_name": map_name,
                    "max_games": max_games,
                    "max_days": max_days,
                },
                "classic_country_options": classic_country_options,
                "update": None,
                "update_form": {
                    "username": username,
                },
            },
        )

    @app.get("/available-games")
    def available_games(
        username: str,
        include: str = "both",
        mode: Optional[Literal["moving", "nm", "nmpz"]] = None,
        max_days: Optional[int] = None,
    ):
        # Hack-free way to avoid expanding function signature everywhere: stash max_days for this call.
        return {"count": _available_games_count(username, include, mode, max_days)}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        usernames = _load_usernames(repo_root)
        default_username = usernames[0] if usernames else ""
        default_include: str = "both"
        default_mode: Optional[Literal["moving", "nm", "nmpz"]] = None
        default_max_games: Optional[int] = None
        default_max_days: Optional[int] = None
        default_min_net: int = -5000
        default_country = ""

        default_classic_mode: Optional[Literal["moving", "nm", "nmpz"]] = None
        default_classic_map_name: str = ""
        default_classic_min_rounds: Optional[int] = None
        default_classic_sort_by: str = "accuracy"

        default_classic_country: str = ""

        country_options = (
            _country_options_for_user(
                default_username,
                default_include,
                default_mode,
                default_max_games,
                default_max_days,
            )
            if default_username
            else []
        )

        analyse_available_games = (
            _available_games_count(default_username, default_include, default_mode, default_max_days)
            if default_username
            else 0
        )
        country_available_games = analyse_available_games

        classic_maps = _classic_maps_for_user(default_username) if default_username else []

        classic_country_options = (
            _classic_country_options_for_user(
                default_username,
                default_classic_mode,
                default_classic_map_name,
                default_max_games,
                default_max_days,
            )
            if default_username
            else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": usernames,
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, default_username)
                if default_username
                else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, default_username)
                if default_username
                else [],
                "analyse": None,
                "analyse_available_games": analyse_available_games,
                "country": None,
                "update": None,
                "update_form": {
                    "username": default_username,
                },
                "classic": None,
                "classic_form": {
                    "username": default_username,
                    "mode": default_classic_mode,
                    "map_name": default_classic_map_name,
                    "max_games": default_max_games,
                    "max_days": default_max_days,
                    "min_rounds": default_classic_min_rounds,
                    "sort_by": default_classic_sort_by,
                },
                "classic_maps": classic_maps,
                "classic_country": None,
                "classic_country_form": {
                    "username": default_username,
                    "country": default_classic_country,
                    "mode": default_classic_mode,
                    "map_name": default_classic_map_name,
                    "max_games": default_max_games,
                    "max_days": default_max_days,
                },
                "classic_country_options": classic_country_options,
                "country_form": {
                    "username": default_username,
                    "country": default_country,
                    "mode": default_mode,
                    "include": default_include,
                    "max_games": default_max_games,
                    "max_days": default_max_days,
                    "min_net": default_min_net,
                },
                "country_available_games": country_available_games,
                "country_options": country_options,
            },
        )

    @app.post("/update-data", response_class=HTMLResponse)
    def update_data(
        request: Request,
        username: str = Form(...),
    ):
        class Args:
            pass

        args = Args()
        args.username = username
        args.max_games = None
        args.overwrite = False

        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
            try:
                fetch_command(args)
            except SystemExit:
                pass
        stdout = stdout_buf.getvalue()
        stderr = stderr_buf.getvalue()
        stats = getattr(args, "_fetch_stats", None)

        if _wants_json(request):
            return JSONResponse(
                {
                    "ok": True,
                    "username": username,
                    "stdout": stdout.strip(),
                    "stderr": stderr.strip(),
                    "stats": stats,
                }
            )

        analyse_available_games = _available_games_count(username, "both", None, None)
        country_available_games = analyse_available_games

        classic_maps = _classic_maps_for_user(username) if username else []
        classic_country_options = (
            _classic_country_options_for_user(username, None, "", None, None) if username else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "analyse": None,
                "analyse_available_games": analyse_available_games,
                "country": None,
                "classic": None,
                "classic_form": {
                    "username": username,
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                    "min_rounds": None,
                    "sort_by": "accuracy",
                },
                "classic_maps": classic_maps,
                "classic_country": None,
                "classic_country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                },
                "classic_country_options": classic_country_options,
                "country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "include": "both",
                    "max_games": None,
                    "max_days": None,
                    "min_net": -5000,
                    "both_correct": False,
                },
                "country_available_games": country_available_games,
                "country_options": (_country_options_for_user(username, "both", None, None, None) if username else []),
                "update": {
                    "form": {
                        "username": username,
                    },
                    "stdout": stdout.strip(),
                    "stderr": stderr.strip(),
                    "stats": stats,
                },
                "update_form": {
                    "username": username,
                },
            },
        )

    @app.post("/analyse", response_class=HTMLResponse)
    def run_analyse(
        request: Request,
        username: str = Form(...),
        analysis_type: Optional[Literal["region", "general", "wrong-country", "win-percentage"]] = Form(None),
        mode: Optional[Literal["moving", "nm", "nmpz"]] = Form(None),
        include: str = Form("both"),
        max_games: Optional[int] = Form(None),
        max_days: Optional[int] = Form(None),
        min_rounds: Optional[int] = Form(None),
    ):
        class Args:
            pass

        args = Args()
        args.username = username
        # Back-compat: older UI used multiple analysis types; these are now merged.
        effective_type = analysis_type
        if effective_type in (None, "", "wrong-country", "win-percentage"):
            effective_type = "general"

        args.type = effective_type if effective_type == "region" else None
        args.mode = mode
        args.include = include
        args.max_games = max_games
        args.max_days = max_days
        args.min_rounds = min_rounds

        stdout, stderr = _run_command_capture(analyse_command, args)

        rows: list[dict[str, Any]]
        if effective_type == "general":
            base_rows = _parse_analyse(stdout, None)
            # Merge wrong-country stats.
            args_wrong = Args()
            args_wrong.username = username
            args_wrong.type = "wrong-country"
            args_wrong.mode = mode
            args_wrong.include = include
            args_wrong.max_games = max_games
            args_wrong.max_days = max_days
            args_wrong.min_rounds = min_rounds

            stdout_wrong, stderr_wrong = _run_command_capture(analyse_command, args_wrong)
            if stderr_wrong.strip():
                stderr = (stderr.strip() + "\n" + stderr_wrong.strip()).strip()
            wrong_rows = _parse_analyse(stdout_wrong, "wrong-country")
            wrong_by_cc = {(r.get("cc") or "").upper(): r for r in wrong_rows}

            rows = []
            for r in base_rows:
                cc = (r.get("cc") or "").upper()
                w = wrong_by_cc.get(cc)
                merged = dict(r)
                wrong_pct = float(w.get("wrong_pct")) if w and w.get("wrong_pct") is not None else float("nan")
                merged["accuracy_pct"] = (100.0 - wrong_pct) if wrong_pct == wrong_pct else float("nan")
                rows.append(merged)
        else:
            rows = _parse_analyse(stdout, effective_type)

        analyse_available_games = _available_games_count(username, include, mode, max_days)
        country_available_games = _available_games_count(username, "both", None, None)

        classic_maps = _classic_maps_for_user(username) if username else []
        classic_country_options = (
            _classic_country_options_for_user(username, None, "", None, None) if username else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "analyse": {
                    "form": {
                        "username": username,
                        "type": effective_type,
                        "mode": mode,
                        "include": include,
                        "max_games": max_games,
                        "max_days": max_days,
                        "min_rounds": min_rounds,
                    },
                    "stderr": stderr.strip(),
                    "rows": rows,
                },
                "analyse_available_games": analyse_available_games,
                "country": None,
                "classic": None,
                "classic_country": None,
                "classic_country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                },
                "classic_country_options": classic_country_options,
                "classic_form": {
                    "username": username,
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                    "sort_by": "accuracy",
                },
                "classic_maps": classic_maps,
                "update": None,
                "update_form": {
                    "username": username,
                },
                "country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "include": "both",
                    "max_games": None,
                    "max_days": None,
                    "min_net": -5000,
                },
                "country_available_games": country_available_games,
                "country_options": (
                    _country_options_for_user(username, "both", None, None, None) if username else []
                ),
            },
        )

    @app.post("/country", response_class=HTMLResponse)
    def run_country(
        request: Request,
        username: str = Form(...),
        country: str = Form(...),
        mode: Optional[Literal["moving", "nm", "nmpz"]] = Form(None),
        include: str = Form("both"),
        max_games: Optional[int] = Form(None),
        max_days: Optional[int] = Form(None),
        min_net: int = Form(-5000),
        both_correct: Optional[str] = Form(None),
    ):
        class Args:
            pass

        args = Args()
        args.username = username
        args.country = country
        args.mode = mode
        args.include = include
        args.max_games = max_games
        args.max_days = max_days
        args.min_net = min_net
        args.both_correct = both_correct is not None

        stdout, stderr = _run_command_capture(country_command, args)
        rows = _parse_country(stdout)

        country_options = _country_options_for_user(username, include, mode, max_games, max_days) if username else []

        analyse_available_games = _available_games_count(username, "both", None, None)
        country_available_games = _available_games_count(username, include, mode, max_days)

        classic_maps = _classic_maps_for_user(username) if username else []
        classic_country_options = (
            _classic_country_options_for_user(username, None, "", None, None) if username else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "analyse": None,
                "analyse_available_games": analyse_available_games,
                "country": {
                    "form": {
                        "username": username,
                        "country": country,
                        "mode": mode,
                        "include": include,
                        "max_games": max_games,
                        "max_days": max_days,
                        "min_net": min_net,
                        "both_correct": both_correct is not None,
                    },
                    "stderr": stderr.strip(),
                    "rows": rows,
                },
                "classic": None,
                "classic_country": None,
                "classic_country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                },
                "classic_country_options": classic_country_options,
                "classic_form": {
                    "username": username,
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                    "sort_by": "accuracy",
                },
                "classic_maps": classic_maps,
                "update": None,
                "update_form": {
                    "username": username,
                },
                "country_form": {
                    "username": username,
                    "country": country,
                    "mode": mode,
                    "include": include,
                    "max_games": max_games,
                    "max_days": max_days,
                    "min_net": min_net,
                    "both_correct": both_correct is not None,
                },
                "country_available_games": country_available_games,
                "country_options": country_options,
            },
        )

    @app.get("/country", response_class=HTMLResponse)
    def get_country(
        request: Request,
        username: str,
        country: str,
        mode: Optional[Literal["moving", "nm", "nmpz"]] = None,
        include: str = "both",
        max_games: Optional[int] = None,
        max_days: Optional[int] = None,
        min_net: int = -5000,
        both_correct: bool = False,
    ):
        class Args:
            pass

        args = Args()
        args.username = username
        args.country = country
        args.mode = mode
        args.include = include
        args.max_games = max_games
        args.max_days = max_days
        args.min_net = min_net
        args.both_correct = both_correct

        stdout, stderr = _run_command_capture(country_command, args)
        rows = _parse_country(stdout)

        country_options = _country_options_for_user(username, include, mode, max_games, max_days) if username else []

        analyse_available_games = _available_games_count(username, "both", None, None)
        country_available_games = _available_games_count(username, include, mode, max_days)

        classic_maps = _classic_maps_for_user(username) if username else []
        classic_country_options = (
            _classic_country_options_for_user(username, None, "", None, None) if username else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "country_teammates": _team_duel_teammates_for_user(repo_root, username) if username else [],
                "analyse": None,
                "analyse_available_games": analyse_available_games,
                "country": {
                    "form": {
                        "username": username,
                        "country": country,
                        "mode": mode,
                        "include": include,
                        "max_games": max_games,
                        "max_days": max_days,
                        "min_net": min_net,
                        "both_correct": both_correct,
                    },
                    "stderr": stderr.strip(),
                    "rows": rows,
                },
                "classic": None,
                "classic_country": None,
                "classic_country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                },
                "classic_country_options": classic_country_options,
                "classic_form": {
                    "username": username,
                    "mode": None,
                    "map_name": "",
                    "max_games": None,
                    "max_days": None,
                    "sort_by": "accuracy",
                },
                "classic_maps": classic_maps,
                "update": None,
                "update_form": {
                    "username": username,
                },
                "country_form": {
                    "username": username,
                    "country": country,
                    "mode": mode,
                    "include": include,
                    "max_games": max_games,
                    "max_days": max_days,
                    "min_net": min_net,
                    "both_correct": both_correct,
                },
                "country_available_games": country_available_games,
                "country_options": country_options,
            },
        )

    return app
