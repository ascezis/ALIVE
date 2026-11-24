"""ALIVE's private workout-state API."""

from contextlib import closing
from datetime import date
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
from threading import Lock
import time
from typing import Annotated, Literal
from urllib.parse import parse_qsl, urlsplit

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from .report_pdf import build_report


BACKEND = Path(__file__).resolve().parent
DATABASE = BACKEND / "data" / "lfk.sqlite3"
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
NonNegative = Annotated[int, Field(ge=0)]
Results = Annotated[list[Literal["done", "skipped"]], Field(max_length=256)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SavedPlan(Model):
    id: str
    name: str
    minutes: NonNegative | None = None
    advisory: str | None = None
    exercises: Annotated[list[dict[str, JsonValue]], Field(min_length=1, max_length=256)]


class ActiveSession(Model):
    planId: str | None = None
    planSnapshot: SavedPlan | None = None
    mode: Literal["video"] | None = None
    startedAt: NonNegative
    elapsedMs: NonNegative = 0
    results: Results

    @model_validator(mode="after")
    def check_position(self):
        if self.planSnapshot and (
            self.planId != self.planSnapshot.id or len(self.results) >= len(self.planSnapshot.exercises)
        ):
            raise ValueError("Active workout position is outside the saved plan")
        return self


class Timer(Model):
    status: Literal["ready", "running", "paused", "finished"] = "ready"
    remainingMs: NonNegative = 0
    endsAt: NonNegative = 0


class Workout(Model):
    mode: Literal["video"] | None = None
    planId: str | None = None
    title: str | None = None
    videoId: str | None = None
    date: str
    duration: NonNegative | None
    results: Results | None = None
    exerciseNames: Annotated[list[str], Field(max_length=256)] | None = None
    note: Annotated[str, Field(max_length=500)] = ""

    @model_validator(mode="after")
    def check_mode(self):
        date.fromisoformat(self.date)
        if self.mode == "video":
            if self.results is not None or not self.videoId:
                raise ValueError("Invalid video workout")
        elif self.duration is None or not self.results:
            raise ValueError("Missing guided workout results")
        if self.exerciseNames is not None and len(self.exerciseNames) != len(self.results or []):
            raise ValueError("Exercise names and results do not match")
        return self


class Day(Model):
    pain: Annotated[int, Field(ge=0, le=10)] | None = None
    stiffness: Annotated[int, Field(ge=0, le=1440)] | None = None
    fatigue: Annotated[int, Field(ge=0, le=10)] | None = None
    workouts: list[Workout] = Field(default_factory=list)


class WorkoutState(Model):
    session: ActiveSession | None = None
    timer: Timer = Field(default_factory=Timer)
    summary: Workout | None = None
    diary: dict[str, Day] = Field(default_factory=dict)

    @model_validator(mode="after")
    def check_state(self):
        if self.session is not None and self.summary is not None:
            raise ValueError("An active session and a pending summary cannot coexist")
        for key, entry in self.diary.items():
            if date.fromisoformat(key).isoformat() != key or any(workout.date != key for workout in entry.workouts):
                raise ValueError("Diary entry has an inconsistent date")
        return self


class Snapshot(Model):
    revision: NonNegative
    state: WorkoutState
    dailyWorkoutGoal: Literal[1, 2] = 1


def daily_workout_goal() -> Literal[1, 2]:
    return 2 if os.environ.get("ALIVE_DAILY_WORKOUT_GOAL") == "2" else 1


class ReportRange(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date

    @model_validator(mode="after")
    def check_period(self):
        if self.start > self.end:
            raise ValueError("The report start is after its end")
        return self


def telegram_user(init_data: str, token: str) -> int:
    pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True, max_num_fields=32)
    fields = dict(pairs)
    if len(fields) != len(pairs):
        raise ValueError("Repeated Telegram fields")
    supplied = fields.pop("hash")
    signed = "\n".join(f"{key}={value}" for key, value in sorted(fields.items()))
    key = hmac.digest(b"WebAppData", token.encode("utf-8"), hashlib.sha256)
    expected = hmac.digest(key, signed.encode("utf-8"), hashlib.sha256).hex()
    if not supplied.isascii() or not hmac.compare_digest(expected, supplied):
        raise ValueError("Invalid Telegram signature")
    age = time.time() - int(fields["auth_date"])
    if not -60 <= age <= 86400:
        raise ValueError("Expired Telegram session")
    user_id = json.loads(fields["user"])["id"]
    if type(user_id) is not int or user_id <= 0:
        raise ValueError("Invalid Telegram user")
    return user_id


def owner(request: Request) -> str:
    if os.environ.get("ALIVE_LOCAL_DEV") == "1":
        origin = request.headers.get("origin")
        from_browser = request.headers.get("sec-fetch-site", "none")
        if (
            request.client is None
            or request.client.host not in LOOPBACK
            or request.url.hostname not in LOOPBACK
            or from_browser not in {"none", "same-origin"}
            or (origin and urlsplit(origin).hostname not in LOOPBACK)
        ):
            raise HTTPException(403, "Local access only")
        return "local"

    token = os.environ.get("ALIVE_TELEGRAM_BOT_TOKEN")
    allowed_id = os.environ.get("ALIVE_TELEGRAM_USER_ID", "")
    if not token or not allowed_id.isdecimal():
        raise HTTPException(503, "Telegram access is not configured")
    init_data = request.headers.get("x-telegram-init-data", "")
    try:
        user_id = telegram_user(init_data, token)
    except (KeyError, TypeError, ValueError):
        raise HTTPException(401, "Open ALIVE from Telegram again") from None
    if user_id != int(allowed_id):
        raise HTTPException(403, "This account cannot access ALIVE")
    return f"telegram:{user_id}"


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    path = Path(path if path is not None else os.environ.get("ALIVE_DATABASE", DATABASE))
    path.parent.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(path, timeout=8)
    database.execute(
        """CREATE TABLE IF NOT EXISTS alive_workout_state (
               owner TEXT PRIMARY KEY, revision INTEGER NOT NULL,
               state_json TEXT NOT NULL CHECK (json_valid(state_json))
           )"""
    )
    return database


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware("http")
async def prevent_api_caching(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.get("/api/state")
def load_state(user: Annotated[str, Depends(owner)]) -> Snapshot:
    with closing(connect()) as database:
        row = database.execute(
            "SELECT revision, state_json FROM alive_workout_state WHERE owner = ?", (user,),
        ).fetchone()
    if row is None:
        return Snapshot(revision=0, state=WorkoutState(), dailyWorkoutGoal=daily_workout_goal())
    return Snapshot(revision=row[0], state=WorkoutState.model_validate_json(row[1]),
                    dailyWorkoutGoal=daily_workout_goal())


@app.put("/api/state")
def save_state(change: Snapshot, user: Annotated[str, Depends(owner)]) -> Snapshot:
    encoded = json.dumps(change.state.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    goal = daily_workout_goal()
    with closing(connect()) as database, database:
        database.execute("BEGIN IMMEDIATE")
        current = database.execute(
            "SELECT revision, state_json FROM alive_workout_state WHERE owner = ?", (user,),
        ).fetchone()
        revision = current[0] if current else 0
        if current and current[1] == encoded:
            return Snapshot(revision=revision, state=change.state, dailyWorkoutGoal=goal)
        if change.revision != revision:
            raise HTTPException(409, "The diary changed in another window")
        revision += 1
        database.execute(
            """INSERT INTO alive_workout_state (owner, revision, state_json) VALUES (?, ?, ?)
               ON CONFLICT(owner) DO UPDATE SET
                   revision = excluded.revision, state_json = excluded.state_json""",
            (user, revision, encoded),
        )
    return Snapshot(revision=revision, state=change.state, dailyWorkoutGoal=goal)


report_files = {}
report_lock = Lock()
REPORT_TTL = 180


@app.post("/api/report")
def prepare_report(period: ReportRange, user: Annotated[str, Depends(owner)]):
    diary = load_state(user).state.diary
    entries = sorted(
        (day, entry) for key, entry in diary.items()
        if period.start <= (day := date.fromisoformat(key)) <= period.end
    )
    content = build_report(period.start, period.end, entries)
    filename = f"ALIVE-report-{period.start.isoformat()}_{period.end.isoformat()}.pdf"
    token = secrets.token_urlsafe(32)
    now = time.monotonic()
    with report_lock:
        for expired in [key for key, item in report_files.items() if item[0] <= now]:
            del report_files[expired]
        if len(report_files) >= 16:
            del report_files[next(iter(report_files))]
        report_files[token] = (now + REPORT_TTL, filename, content)
    return {"path": f"/api/report/download/{token}", "filename": filename, "expiresIn": REPORT_TTL}


@app.api_route("/api/report/download/{token}", methods=["GET", "HEAD"])
def download_report(token: str, request: Request):
    with report_lock:
        report = report_files.get(token)
        if report is None or report[0] <= time.monotonic():
            report_files.pop(token, None)
            raise HTTPException(404, "Report download has expired")
    _, filename, content = report
    return Response(
        b"" if request.method == "HEAD" else content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(content)),
            "Access-Control-Allow-Origin": "https://web.telegram.org",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
        },
    )


dist = BACKEND.parent / "miniapp" / "dist"
if dist.is_dir():
    app.mount("/", StaticFiles(directory=dist, html=True), name="miniapp")
