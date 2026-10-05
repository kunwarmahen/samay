"""What Samay keeps: the schedules, and every time one ran.

One SQLite file, ``samay.sqlite3`` in the state directory. Two tables,
because there are two questions a person asks -- "what have I set up?"
and "what happened?" -- and they are asked at different moments.

A SCHEDULE IS A PROMISE; A RUN IS A RECEIPT. A schedule row changes
(paused, resumed, its next time moved on); a run row is written once
when the run starts and once when it ends, and never again. A run whose
end never arrived -- the process died under it -- is said to be
``interrupted`` on the next start, rather than left looking as if it
were still going.

EVERY TIME IS A TIME IN UTC, as ISO text. The schedule's own time zone
is a column; a time is turned into the person's clock only when it is
shown. Text rather than a number so the file can be read with the
``sqlite3`` shell and nothing else.

A missed time is a run too (``missed``, ``skipped``, ``busy``): a person
asking "did my 8 o'clock check happen?" deserves a row that says no and
why, not an absence they have to notice.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field, fields
from datetime import UTC, datetime
from pathlib import Path

#: How a run ended. ``ok`` and ``quiet`` finished; ``quiet`` had nothing
#: worth telling. The rest did not do the work, each for its own reason.
OUTCOMES = ("ok", "quiet", "failed", "needs_person", "timed_out", "busy",
            "held", "missed", "skipped", "interrupted", "running")

#: Runs that count towards pausing a schedule after too many in a row.
FAILURES = ("failed", "timed_out", "interrupted")

NOTIFY = ("always", "when_new", "never")
RUNNERS = ("direct", "dvara")
STATES = ("active", "paused", "done")

#: A full answer is kept, but not without limit: a run that pasted a
#: whole web page into its reply should not make the file grow by it
#: every hour.
REPLY_CAP = 20_000


def now_utc() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime | None) -> str | None:
    return None if moment is None else moment.astimezone(UTC).isoformat(
        timespec="seconds")


def from_iso(text: str | None) -> datetime | None:
    return None if not text else datetime.fromisoformat(text)


@dataclass
class Schedule:
    id: str
    owner: str
    prompt: str
    when: dict
    tz: str
    runner: str = "direct"
    agent: str = ""                  # package dir (direct) or name (dvara)
    notify: str = "when_new"
    allow_tools: list[str] = field(default_factory=list)
    time_limit: int = 600            # seconds
    browser_profile: str = ""
    state: str = "active"
    paused_because: str = ""
    created_at: str = ""
    created_via: str = "cli"
    next_at: str | None = None
    failures: int = 0                # in a row; reset by any run that finished

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class Run:
    id: str
    schedule: str
    due_at: str
    outcome: str = "running"
    started_at: str | None = None
    ended_at: str | None = None
    summary: str = ""
    reply: str = ""
    cost_usd: float = 0.0
    notified: bool = False
    needs: list[str] = field(default_factory=list)
    #: Tools the run reached for that were not allowed ahead of time.
    #: Not a failure -- the model was told no -- but worth seeing: it is
    #: how a person learns what to allow next time.
    refused: list[str] = field(default_factory=list)
    detail: str = ""
    dvara_run_id: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


_LIST_COLUMNS = {"when", "allow_tools", "needs", "refused"}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schedule (
    id TEXT PRIMARY KEY,
    owner TEXT NOT NULL,
    prompt TEXT NOT NULL,
    "when" TEXT NOT NULL,
    tz TEXT NOT NULL,
    runner TEXT NOT NULL,
    agent TEXT NOT NULL,
    notify TEXT NOT NULL,
    allow_tools TEXT NOT NULL,
    time_limit INTEGER NOT NULL,
    browser_profile TEXT NOT NULL,
    state TEXT NOT NULL,
    paused_because TEXT NOT NULL,
    created_at TEXT NOT NULL,
    created_via TEXT NOT NULL,
    next_at TEXT,
    failures INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS run (
    id TEXT PRIMARY KEY,
    schedule TEXT NOT NULL,
    due_at TEXT NOT NULL,
    outcome TEXT NOT NULL,
    started_at TEXT,
    ended_at TEXT,
    summary TEXT NOT NULL,
    reply TEXT NOT NULL,
    cost_usd REAL NOT NULL,
    notified INTEGER NOT NULL,
    needs TEXT NOT NULL,
    refused TEXT NOT NULL,
    detail TEXT NOT NULL,
    dvara_run_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS run_by_schedule ON run (schedule, due_at);
"""


class Store:
    """The file, and the only code that touches it."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _db(self) -> Iterator[sqlite3.Connection]:
        # A connection per use: the ticker writes from worker threads, the
        # CLI from another process, and SQLite's own locking is the thing
        # that keeps them apart. Short transactions, nothing held open.
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    # -- schedules ---------------------------------------------------------

    def add(self, schedule: Schedule) -> Schedule:
        if not schedule.id:
            schedule.id = self._new_id("schedule")
        if not schedule.created_at:
            schedule.created_at = iso(now_utc())
        self._put("schedule", schedule)
        return schedule

    def get(self, schedule_id: str) -> Schedule | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM schedule WHERE id = ?",
                             (schedule_id,)).fetchone()
        return _load(Schedule, row) if row else None

    def schedules(self, owner: str | None = None,
                  state: str | None = None) -> list[Schedule]:
        query, args = "SELECT * FROM schedule", []
        where = []
        if owner is not None:
            where.append("owner = ?")
            args.append(owner)
        if state is not None:
            where.append("state = ?")
            args.append(state)
        if where:
            query += " WHERE " + " AND ".join(where)
        with self._db() as db:
            rows = db.execute(query + " ORDER BY created_at", args).fetchall()
        return [_load(Schedule, r) for r in rows]

    def update(self, schedule_id: str, **changes) -> None:
        if not changes:
            return
        cols = ", ".join(f'"{k}" = ?' for k in changes)
        with self._db() as db:
            db.execute(f"UPDATE schedule SET {cols} WHERE id = ?",
                       [*(_dump(k, v) for k, v in changes.items()), schedule_id])

    def delete(self, schedule_id: str) -> bool:
        """Forget a schedule and its runs. A deleted schedule's history
        goes with it: what is kept about something you asked to be gone
        is not yours to find later."""
        with self._db() as db:
            gone = db.execute("DELETE FROM schedule WHERE id = ?",
                              (schedule_id,)).rowcount
            db.execute("DELETE FROM run WHERE schedule = ?", (schedule_id,))
        return bool(gone)

    # -- runs --------------------------------------------------------------

    def start_run(self, schedule_id: str, due_at: datetime,
                  outcome: str = "running", at: datetime | None = None) -> Run:
        run = Run(id=self._new_id("run"), schedule=schedule_id,
                  due_at=iso(due_at), outcome=outcome,
                  started_at=iso(at or now_utc()))
        if outcome != "running":
            run.ended_at = run.started_at
        self._put("run", run)
        return run

    def finish_run(self, run: Run, at: datetime | None = None) -> None:
        run.ended_at = run.ended_at or iso(at or now_utc())
        run.reply = run.reply[:REPLY_CAP]
        self._put("run", run)

    def runs(self, schedule_id: str | None = None, limit: int = 50,
             owner: str | None = None) -> list[Run]:
        query = "SELECT run.* FROM run"
        where, args = [], []
        if owner is not None:
            query += " JOIN schedule ON schedule.id = run.schedule"
            where.append("schedule.owner = ?")
            args.append(owner)
        if schedule_id is not None:
            where.append("run.schedule = ?")
            args.append(schedule_id)
        if where:
            query += " WHERE " + " AND ".join(where)
        query += " ORDER BY run.started_at DESC, run.due_at DESC LIMIT ?"
        with self._db() as db:
            rows = db.execute(query, [*args, limit]).fetchall()
        return [_load(Run, r) for r in rows]

    def last_finished(self, schedule_id: str) -> Run | None:
        """The last run that did the work, for "what's new since"."""
        with self._db() as db:
            row = db.execute(
                "SELECT * FROM run WHERE schedule = ? AND outcome IN "
                "('ok', 'quiet') ORDER BY started_at DESC LIMIT 1",
                (schedule_id,)).fetchone()
        return _load(Run, row) if row else None

    def interrupt_unfinished(self, at: datetime | None = None) -> int:
        """Runs a dead process left ``running``: said to be interrupted."""
        with self._db() as db:
            return db.execute(
                "UPDATE run SET outcome = 'interrupted', ended_at = ?, "
                "summary = 'interrupted', detail = 'Samay stopped while this "
                "was running; it was not run again.' WHERE outcome = 'running'",
                (iso(at or now_utc()),)).rowcount

    # -- plumbing ----------------------------------------------------------

    def _new_id(self, table: str) -> str:
        with self._db() as db:
            while True:
                candidate = secrets.token_hex(4)
                if not db.execute(f"SELECT 1 FROM {table} WHERE id = ?",
                                  (candidate,)).fetchone():
                    return candidate

    def _put(self, table: str, record) -> None:
        names = [f.name for f in fields(record)]
        cols = ", ".join(f'"{n}"' for n in names)
        marks = ", ".join("?" for _ in names)
        values = [_dump(n, getattr(record, n)) for n in names]
        with self._db() as db:
            db.execute(f"INSERT OR REPLACE INTO {table} ({cols}) VALUES ({marks})",
                       values)


def _dump(name: str, value):
    if name in _LIST_COLUMNS:
        return json.dumps(value)
    if isinstance(value, bool):
        return int(value)
    return value


def _load(cls, row: sqlite3.Row):
    data = {}
    for f in fields(cls):
        value = row[f.name]
        if f.name in _LIST_COLUMNS:
            value = json.loads(value)
        elif f.name == "notified":
            value = bool(value)
        data[f.name] = value
    return cls(**data)
