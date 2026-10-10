"""What Samay can tell a harness: is it running, where, and how to talk to it.

A harness that wants to offer its agent "do this later" needs three
answers: does this machine have Samay, is its clock running (a schedule
made while nothing is serving will not run on time, and the person
should hear that), and how to start the tools an agent uses to make one.
``report()`` is all three as one dict, and ``samay status --json``
prints the same dict -- the shape Setu's ``status --json`` set for this
family of programs.

ONE ANSWER, TWO ROADS. A harness with Samay in its own Python calls
``report()``; one without runs the command and reads the JSON. Both go
through this function, so they cannot disagree.

THE CLOCK HOLDS A LOCK, NOT A PID. ``samay serve`` takes an exclusive
``flock`` on ``serve.lock`` for as long as it runs, and "is it serving?"
is "is that lock held?". A pid written to a file says nothing once the
process is gone. After a crash, the number may belong to something else
-- in a fresh container, often the new ``samay serve`` itself, since
pids start again at 1 -- and the clock would refuse to start because it
believed it was already running. And a pid means nothing at all to a
program in another container. A lock is released by the kernel however
its holder dies, and every process that opens the same file sees it,
whichever namespace it is in. Taking it is also the check, so two
``samay serve`` started at once cannot both win.

WHERE ANSWERS GO is the running clock's: ``dvara`` (its address) and
``local_to`` (who hears a schedule made at this computer), as written
by ``samay serve``. A harness runs ``samay status`` with its own
environment, which is not the clock's.

NO SECRET IS IN IT. The page's token is not here; a harness that wants
the page sends the person to ``samay serve``'s own printed address. The
``format`` field names the shape, and a reader should refuse one it does
not know rather than guess.
"""

from __future__ import annotations

import fcntl
import json
import os
import shutil
import sys
from pathlib import Path

from samay import __version__
from samay.store import Store

FORMAT = "samay.status.v1"


def samay_command() -> str:
    beside = Path(sys.executable).parent / "samay"
    if beside.exists():
        return str(beside)
    return shutil.which("samay") or "samay"


LOCK_FILE = "serve.lock"


def hold_clock(state: Path):
    """Take the clock's lock for this process's lifetime; the open file
    (keep it open), or None when another ``samay serve`` holds it."""
    held = open(state / LOCK_FILE, "a")  # noqa: SIM115 -- held until exit
    try:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        held.close()
        return None
    return held


def serving(state: Path) -> dict | None:
    """What ``samay serve`` wrote when it started, if it is still running."""
    try:
        with open(state / LOCK_FILE) as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                pass                          # held: the clock is running
            else:
                return None                   # nobody holds it
    except OSError:
        return None
    try:
        info = json.loads((state / "serve.json").read_text())
    except (OSError, ValueError):
        info = {}
    return info if isinstance(info, dict) else {}


def report(state: Path, store: Store) -> dict:
    counts = {"active": 0, "paused": 0, "done": 0}
    for schedule in store.schedules():
        counts[schedule.state] = counts.get(schedule.state, 0) + 1
    served = serving(state)
    # the running clock's own answer first: it is the one that sends
    dvara = ((served or {}).get("dvara")
             or os.environ.get("SAMAY_DVARA_URL", "").strip() or None)
    return {
        "format": FORMAT,
        "version": __version__,
        "state": str(state),
        "serving": served is not None,
        "url": served.get("url") if served else None,
        "schedules": counts,
        "dvara": dvara,
        # Who hears a schedule made at this computer (``local``), through
        # Dvara: the running clock's $SAMAY_DVARA_ACTOR, or "" for nobody.
        "local_to": str((served or {}).get("local_to") or ""),
        # How a harness starts the agent's tools: add "--for WHO".
        "mcp": {"command": samay_command(),
                "args": ["--state", str(state), "mcp"]},
    }
