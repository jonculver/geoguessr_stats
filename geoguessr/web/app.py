from __future__ import annotations

import io
import json
import re
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any, Literal, Optional

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from geoguessr.__main__ import analyse_command, country_command


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
        func(args_obj)
    return stdout_buf.getvalue(), stderr_buf.getvalue()


_ANALYSE_ROW_RE = re.compile(
    r"^\s*(?P<idx>\d+)\s+(?P<cc>[A-Z?]{2})\s+(?P<name>.*?):\s+avg_net=(?P<avg>[-0-9.]+)\s+rounds=(?P<rounds>\d+)\s+win%=(?P<win>[-0-9.]+)\s*$"
)

_WRONG_COUNTRY_ROW_RE = re.compile(
    r"^\s*(?P<idx>\d+)\s+(?P<cc>[A-Z?]{2})\s+(?P<name>.*?):\s+wrong%=(?P<wrong_pct>[-0-9.]+)\s+wrong=(?P<wrong>\d+)\s+rounds=(?P<rounds>\d+)\s*$"
)

_COUNTRY_LINE_RE = re.compile(
    r"^\s*(?P<date>\d{4}-\d{2}-\d{2})\s+(?:duel=(?P<duel>\S+)\s+)?(?:mode=(?P<mode>\S+)\s+)?net=(?P<net>-?\d+)\s+round=(?P<round>\d+)\s+correct=(?P<correct>[YN?])\s*$"
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
                "duel_url": duel_url,
                "sv_url": sv_url,
            }
        )
        i += 3

    return out


def _country_options_for_user(
    username: str,
    include: Literal["ranked", "unranked", "both"],
    mode: Optional[Literal["moving", "nm", "nmpz"]],
    max_games: Optional[int],
) -> list[dict[str, str]]:
    class Args:
        pass

    args = Args()
    args.username = username
    args.type = None
    args.mode = mode
    args.include = include
    args.max_games = max_games
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

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        usernames = _load_usernames(repo_root)
        default_username = usernames[0] if usernames else ""
        default_include: Literal["ranked", "unranked", "both"] = "both"
        default_mode: Optional[Literal["moving", "nm", "nmpz"]] = None
        default_max_games: Optional[int] = None
        default_country = ""

        country_options = (
            _country_options_for_user(
                default_username,
                default_include,
                default_mode,
                default_max_games,
            )
            if default_username
            else []
        )

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": usernames,
                "analyse": None,
                "country": None,
                "country_form": {
                    "username": default_username,
                    "country": default_country,
                    "mode": default_mode,
                    "include": default_include,
                    "max_games": default_max_games,
                },
                "country_options": country_options,
            },
        )

    @app.post("/analyse", response_class=HTMLResponse)
    def run_analyse(
        request: Request,
        username: str = Form(...),
        analysis_type: Optional[Literal["region", "wrong-country", "win-percentage"]] = Form(None),
        mode: Optional[Literal["moving", "nm", "nmpz"]] = Form(None),
        include: Literal["ranked", "unranked", "both"] = Form("both"),
        max_games: Optional[int] = Form(None),
        min_rounds: Optional[int] = Form(None),
    ):
        class Args:
            pass

        args = Args()
        args.username = username
        args.type = analysis_type
        args.mode = mode
        args.include = include
        args.max_games = max_games
        args.min_rounds = min_rounds

        stdout, stderr = _run_command_capture(analyse_command, args)
        rows = _parse_analyse(stdout, analysis_type)

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse": {
                    "form": {
                        "username": username,
                        "type": analysis_type,
                        "mode": mode,
                        "include": include,
                        "max_games": max_games,
                        "min_rounds": min_rounds,
                    },
                    "stderr": stderr.strip(),
                    "rows": rows,
                },
                "country": None,
                "country_form": {
                    "username": username,
                    "country": "",
                    "mode": None,
                    "include": "both",
                    "max_games": None,
                },
                "country_options": (
                    _country_options_for_user(username, "both", None, None) if username else []
                ),
            },
        )

    @app.post("/country", response_class=HTMLResponse)
    def run_country(
        request: Request,
        username: str = Form(...),
        country: str = Form(...),
        mode: Optional[Literal["moving", "nm", "nmpz"]] = Form(None),
        include: Literal["ranked", "unranked", "both"] = Form("both"),
        max_games: Optional[int] = Form(None),
    ):
        class Args:
            pass

        args = Args()
        args.username = username
        args.country = country
        args.mode = mode
        args.include = include
        args.max_games = max_games

        stdout, stderr = _run_command_capture(country_command, args)
        rows = _parse_country(stdout)

        country_options = _country_options_for_user(username, include, mode, max_games) if username else []

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse": None,
                "country": {
                    "form": {
                        "username": username,
                        "country": country,
                        "mode": mode,
                        "include": include,
                        "max_games": max_games,
                    },
                    "stderr": stderr.strip(),
                    "rows": rows,
                },
                "country_form": {
                    "username": username,
                    "country": country,
                    "mode": mode,
                    "include": include,
                    "max_games": max_games,
                },
                "country_options": country_options,
            },
        )

    @app.get("/country", response_class=HTMLResponse)
    def get_country(
        request: Request,
        username: str,
        country: str,
        mode: Optional[Literal["moving", "nm", "nmpz"]] = None,
        include: Literal["ranked", "unranked", "both"] = "both",
        max_games: Optional[int] = None,
    ):
        class Args:
            pass

        args = Args()
        args.username = username
        args.country = country
        args.mode = mode
        args.include = include
        args.max_games = max_games

        stdout, stderr = _run_command_capture(country_command, args)
        rows = _parse_country(stdout)

        country_options = _country_options_for_user(username, include, mode, max_games) if username else []

        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "usernames": _load_usernames(repo_root),
                "analyse": None,
                "country": {
                    "form": {
                        "username": username,
                        "country": country,
                        "mode": mode,
                        "include": include,
                        "max_games": max_games,
                    },
                    "stderr": stderr.strip(),
                    "rows": rows,
                },
                "country_form": {
                    "username": username,
                    "country": country,
                    "mode": mode,
                    "include": include,
                    "max_games": max_games,
                },
                "country_options": country_options,
            },
        )

    return app
