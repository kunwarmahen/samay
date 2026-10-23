"""What Samay keeps on this computer, for a backup to take.

A backup of the house (Sarathi's ``sarathi backup``) is one file holding
every program's own files, and each program says where its are --
``samay keeps --json``, asked the way ``status --json`` is -- so the
program that packs it knows nothing of what is inside.

Samay's is its state folder: the one file of schedules and the logbook
of every run (``samay.sqlite3``), the page's key, and each run's working
folder (what a run saved). The file is SQLite, and the backup copies it
with SQLite's own backup, so a run finishing mid-copy is never half in it.

WHAT IS LEFT OUT: the record of a running clock (``serve.json``, and its
lock). Restored on another computer, it would name a process that isn't
there; ``samay serve`` writes a new one when it starts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

FORMAT = "samay.keeps.v1"
LEAVE_OUT = ["serve.json", "serve.lock"]


def report(state: Path) -> dict[str, Any]:
    keeps = [{"id": "state", "path": str(state.resolve()),
              "what": "your schedules, the logbook of every run, and what each run saved",
              "leave_out": LEAVE_OUT, "exists": state.exists()}]
    return {"format": FORMAT, "keeps": keeps}
