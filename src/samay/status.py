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

NO SECRET IS IN IT. The page's token is not here; a harness that wants
the page sends the person to ``samay serve``'s own printed address. The
``format`` field names the shape, and a reader should refuse one it does
not know rather than guess.
"""

from __future__ import annotations

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


def serving(state: Path) -> dict | None:
    """What ``samay serve`` wrote when it started, if it is still running."""
    try:
        info = json.loads((state / "serve.json").read_text())
        os.kill(int(info["pid"]), 0)
        return info
    except (OSError, ValueError, KeyError, TypeError):
        return None


def report(state: Path, store: Store) -> dict:
    counts = {"active": 0, "paused": 0, "done": 0}
    for schedule in store.schedules():
        counts[schedule.state] = counts.get(schedule.state, 0) + 1
    served = serving(state)
    dvara = os.environ.get("SAMAY_DVARA_URL", "").strip() or None
    return {
        "format": FORMAT,
        "version": __version__,
        "state": str(state),
        "serving": served is not None,
        "url": served.get("url") if served else None,
        "schedules": counts,
        "dvara": dvara,
        # How a harness starts the agent's tools: add "--for WHO".
        "mcp": {"command": samay_command(),
                "args": ["--state", str(state), "mcp"]},
    }
