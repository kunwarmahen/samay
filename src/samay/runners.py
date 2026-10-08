"""Who does the work when a time comes: never Samay itself.

Samay is a clock and a logbook. When a schedule is due it hands a prompt
to a RUNNER and writes down what came back. Every runner gives back the
same thing -- a ``RunResult`` -- so the clock does not know or care
which road the turn took.

THE DIRECT ROAD (this module) runs Yantra as a program:

    yantra --agent DIR --cwd WORK --json --unattended \\
           --allow-tools 'browser_*' --prompt "..."

and reads the one JSON object Yantra prints. A PROCESS, NOT AN IMPORT,
for three reasons. A turn that hangs -- a page that never finishes
loading -- can be killed, browser and all, by killing its process
group; a thread cannot be. Yantra usually lives in its own environment
with its own ``.env``, and a program is the one interface that does not
care. And Samay stays a small thing with no dependency on the framework
it schedules: the JSON's ``format`` is the whole contract, and a format
it does not know is refused rather than guessed at.

The Dvara road -- the same turn, run as a person through Dvara, so their
allowance, rules and channels apply -- is a second runner with the same
shape.

WHERE YANTRA RUNS FROM. Yantra reads ``.env`` from the directory it
starts in, which is where a person keeps their model and keys. So the
process starts in ``$SAMAY_YANTRA_HOME`` when it is set (typically the
Yantra checkout), and the agent's tools are confined to a work folder
of the schedule's own with ``--cwd``, so a scheduled run never writes
into the place it was started from.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from samay.store import Schedule

#: The only shape of ``yantra --json`` this reads.
YANTRA_FORMAT = "yantra.run.v1"

#: How long a killed run gets to exit after SIGTERM before SIGKILL.
KILL_GRACE = 5.0

#: The tail of a failed run's stderr kept as its detail.
STDERR_TAIL = 15


@dataclass
class RunResult:
    ok: bool
    text: str = ""
    stop_reason: str = ""
    detail: str = ""
    cost_usd: float = 0.0
    needs: list[str] = field(default_factory=list)
    busy: list[str] = field(default_factory=list)
    refused: list[str] = field(default_factory=list)
    timed_out: bool = False
    #: The turn stopped to wait for the person's approval (the Dvara road:
    #: they were asked, and have not answered yet).
    held: bool = False
    #: Not run at all, and why (``detail``): the phone was in use, or
    #: stayed locked. Not a failure.
    skipped: bool = False
    dvara_run_id: str = ""


class Runner(Protocol):
    def run(self, schedule: Schedule, prompt: str) -> RunResult: ...


class RunnerMissing(RuntimeError):
    """The program a runner needs is not where it was looked for."""


def find_yantra() -> list[str]:
    """The command that starts Yantra: ``$SAMAY_YANTRA`` (may be several
    words, e.g. ``uv run --project ~/yantra yantra``), else ``yantra``
    beside this Python, else on PATH."""
    configured = os.environ.get("SAMAY_YANTRA", "").strip()
    if configured:
        return shlex.split(configured)
    beside = Path(sys.executable).parent / "yantra"
    if beside.exists():
        return [str(beside)]
    found = shutil.which("yantra")
    if found:
        return [found]
    raise RunnerMissing(
        "cannot find yantra: set SAMAY_YANTRA to the command that starts it "
        "(e.g. SAMAY_YANTRA='uv run --project ~/yantra yantra')")


class DirectRunner:
    """Run the turn as a Yantra process on this machine."""

    def __init__(self, work: Path, *, command: list[str] | None = None,
                 home: Path | None = None) -> None:
        self.work = Path(work)
        self.command = command
        raw_home = os.environ.get("SAMAY_YANTRA_HOME", "").strip()
        self.home = home or (Path(raw_home).expanduser() if raw_home else None)

    def argv(self, schedule: Schedule, prompt: str) -> list[str]:
        command = self.command or find_yantra()
        argv = [*command, "--cwd", str(self.work / schedule.id),
                "--json", "--unattended"]
        if schedule.agent:
            argv += ["--agent", schedule.agent]
        for glob in schedule.allow_tools:
            argv += ["--allow-tools", glob]
        return [*argv, "--prompt", prompt]

    def env(self, schedule: Schedule) -> dict[str, str]:
        env = {**os.environ, "YANTRA_UNATTENDED": "1"}
        if schedule.browser_profile:
            env["YANTRA_BROWSER_PROFILE"] = schedule.browser_profile
        return env

    def run(self, schedule: Schedule, prompt: str) -> RunResult:
        try:
            argv = self.argv(schedule, prompt)
        except RunnerMissing as exc:
            return RunResult(ok=False, stop_reason="error", detail=str(exc))
        (self.work / schedule.id).mkdir(parents=True, exist_ok=True)
        cwd = self.home if self.home and self.home.is_dir() else self.work
        try:
            # A session of its own, so the browser the turn started goes
            # down with it when the time limit is up.
            proc = subprocess.Popen(argv, cwd=cwd, env=self.env(schedule),
                                    stdin=subprocess.DEVNULL,
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE, text=True,
                                    start_new_session=True)
        except OSError as exc:
            return RunResult(ok=False, stop_reason="error",
                             detail=f"could not start {argv[0]}: {exc}")
        try:
            out, err = proc.communicate(timeout=schedule.time_limit)
        except subprocess.TimeoutExpired:
            out, err = _kill(proc)
            result = _read(out, err)
            result.ok = False
            result.timed_out = True
            result.stop_reason = "timed_out"
            result.detail = (f"stopped after {schedule.time_limit}s, the "
                             "time limit for this schedule")
            return result
        return _read(out, err)


def _kill(proc: subprocess.Popen) -> tuple[str, str]:
    for sig, wait in ((signal.SIGTERM, KILL_GRACE), (signal.SIGKILL, None)):
        try:
            os.killpg(proc.pid, sig)
        except ProcessLookupError:
            break
        try:
            return proc.communicate(timeout=wait)
        except subprocess.TimeoutExpired:
            continue
    return proc.communicate()


def _read(out: str, err: str) -> RunResult:
    """The JSON line Yantra printed, or a failure that says why not."""
    for line in reversed((out or "").splitlines()):
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        if data.get("format") != YANTRA_FORMAT:
            return RunResult(
                ok=False, stop_reason="error",
                detail=f"yantra answered in a format this Samay does not "
                       f"know ({data.get('format')!r}; want {YANTRA_FORMAT})")
        return RunResult(
            ok=bool(data.get("ok")), text=str(data.get("text") or ""),
            stop_reason=str(data.get("stop_reason") or ""),
            detail=str(data.get("detail") or ""),
            cost_usd=float(data.get("cost_usd") or 0.0),
            needs=[str(n) for n in data.get("needs_person") or []],
            busy=[str(b) for b in data.get("busy") or []],
            refused=[str(r) for r in data.get("refused") or []])
    tail = "\n".join((err or "").strip().splitlines()[-STDERR_TAIL:])
    return RunResult(ok=False, stop_reason="error",
                     detail=tail or "yantra printed no answer")
