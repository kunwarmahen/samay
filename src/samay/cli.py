"""`samay`: set something to run later, see what ran, take it back.

    samay preview "every 3h"                    how a 'when' reads, and its next times
    samay add "check my mail; tell me what needs me" --when "every 2h"
    samay add "what's new on x.com/home?" --when "at 08:00 on weekdays" \\
          --agent ~/agents/reader --allow-tools 'browser_*' --notify always
    samay list                                  every schedule, its next time, its last run
    samay show ID                               one schedule in full
    samay runs [ID]                             what happened, newest first
    samay pause ID | resume ID | rm ID
    samay run-now ID                            once, now, here -- and wait for it
    samay serve                                 the clock: runs what is due, until stopped

``--when`` takes the short form (``every 30m between 09:00-18:00 on
mon-fri``, ``at 08:00,20:00``, ``once 2026-10-06T15:00``, ``cron 0 */2 *
* *``) or the same thing as JSON (``{"every": "3h"}``) -- which is what
an agent sends.

``samay serve`` has to be running for anything to run on time. The
other commands only read and change the file, so they work whether it
is running or not, and it notices a new schedule within half a minute.

State lives in ``~/.samay`` (``--state`` or ``$SAMAY_STATE``). Which
Yantra runs the work: ``$SAMAY_YANTRA`` (the command) and
``$SAMAY_YANTRA_HOME`` (where it starts, for its ``.env``).
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path
from zoneinfo import ZoneInfo

from samay import __version__, schedules
from samay.clock import Clock
from samay.runners import DirectRunner
from samay.store import NOTIFY, Run, Schedule, Store, from_iso


def state_dir(flag: str | None) -> Path:
    raw = flag or os.environ.get("SAMAY_STATE", "").strip() or "~/.samay"
    return Path(raw).expanduser()


def open_store(state: Path) -> Store:
    return Store(state / "samay.sqlite3")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="samay", description="Run an agent's work on a schedule.")
    parser.add_argument("--state", metavar="DIR",
                        help="where schedules and runs are kept "
                             "(default: $SAMAY_STATE or ~/.samay)")
    parser.add_argument("--version", action="version",
                        version=f"samay {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("preview", help="check a 'when' and say it in words")
    p.add_argument("when")
    p.add_argument("--tz", help="time zone (default: $SAMAY_TZ, else this machine's)")
    p.add_argument("--json", action="store_true", dest="json_out")

    p = sub.add_parser("add", help="add a schedule")
    p.add_argument("prompt", help="what the agent is asked each time")
    p.add_argument("--when", required=True,
                   help="e.g. 'every 3h', 'at 08:00 on mon-fri', or JSON")
    p.add_argument("--tz")
    p.add_argument("--agent", default="", metavar="DIR",
                   help="the agent package to run (default: plain Yantra)")
    p.add_argument("--notify", choices=NOTIFY, default="when_new",
                   help="send every answer, only news (default), or none")
    p.add_argument("--allow-tools", action="append", default=[],
                   metavar="GLOB", dest="allow_tools",
                   help="tools that may run without asking (repeatable), "
                        "e.g. 'browser_*'; anything else that changes "
                        "something is refused")
    p.add_argument("--time-limit", type=int,
                   default=schedules.DEFAULT_TIME_LIMIT, metavar="SECONDS",
                   dest="time_limit")
    p.add_argument("--browser-profile", default="", metavar="DIR",
                   dest="browser_profile",
                   help="a browser profile of this schedule's own (sign in "
                        "there once with: yantra --browse-login URL)")
    p.add_argument("--json", action="store_true", dest="json_out")

    p = sub.add_parser("list", help="every schedule")
    p.add_argument("--json", action="store_true", dest="json_out")

    for name, text in (("show", "one schedule in full"),
                       ("pause", "stop running it, keep it"),
                       ("resume", "start again, from now"),
                       ("rm", "remove it, and its history"),
                       ("run-now", "run it once, now, and wait")):
        p = sub.add_parser(name, help=text)
        p.add_argument("id")
        p.add_argument("--json", action="store_true", dest="json_out")

    p = sub.add_parser("runs", help="what happened, newest first")
    p.add_argument("id", nargs="?")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true", dest="json_out")

    sub.add_parser("serve", help="the clock: run what is due, until stopped")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    state = state_dir(args.state)
    try:
        store = open_store(state)
    except OSError as exc:
        print(f"error: cannot open {state}: {exc}", file=sys.stderr)
        return 2
    try:
        return _dispatch(args, store, state)
    except schedules.ScheduleError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args, store: Store, state: Path) -> int:
    cmd = args.command
    if cmd == "preview":
        said = schedules.preview(args.when, args.tz)
        print(json.dumps(said) if args.json_out else said["sentence"])
        return 0
    if cmd == "add":
        schedule = schedules.create(
            store, prompt=args.prompt, when=args.when, tz=args.tz,
            agent=args.agent, notify=args.notify, allow_tools=args.allow_tools,
            time_limit=args.time_limit, browser_profile=args.browser_profile)
        if args.json_out:
            print(json.dumps(_card(schedule)))
        else:
            print(f"added {schedule.id}: {schedules.sentence(schedule)}")
            if not _serving(state):
                print("samay serve is not running: nothing runs on time until "
                      "it is")
        return 0
    if cmd == "list":
        found = store.schedules()
        if args.json_out:
            print(json.dumps([_card(s, store) for s in found]))
            return 0
        if not found:
            print("no schedules (samay add PROMPT --when 'every 3h')")
        for schedule in found:
            _print_schedule(schedule, store)
        return 0
    if cmd == "runs":
        if args.id:
            schedule = schedules.find(store, args.id)
            runs = store.runs(schedule.id, limit=args.limit)
        else:
            runs = store.runs(limit=args.limit)
        if args.json_out:
            print(json.dumps([r.as_dict() for r in runs]))
            return 0
        if not runs:
            print("no runs yet")
        zones = {s.id: ZoneInfo(s.tz) for s in store.schedules()}
        for run in runs:
            _print_run(run, zones.get(run.schedule), with_schedule=not args.id)
        return 0
    if cmd == "serve":
        return _serve(store, state)

    schedule = schedules.find(store, args.id)
    if cmd == "show":
        if args.json_out:
            print(json.dumps(_card(schedule, store)))
            return 0
        _print_schedule(schedule, store, full=True)
        return 0
    if cmd == "pause":
        schedule = schedules.pause(store, schedule.id)
        print(json.dumps(_card(schedule)) if args.json_out
              else f"paused {schedule.id}")
        return 0
    if cmd == "resume":
        schedule = schedules.resume(store, schedule.id)
        print(json.dumps(_card(schedule)) if args.json_out
              else f"resumed {schedule.id}: {schedules.sentence(schedule)}")
        return 0
    if cmd == "rm":
        schedules.remove(store, schedule.id)
        print(json.dumps({"removed": schedule.id}) if args.json_out
              else f"removed {schedule.id}")
        return 0
    if cmd == "run-now":
        clock = Clock(store, _runners(state))
        try:
            run = clock.run_now(schedule.id)
        except RuntimeError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        finally:
            clock.close()
        if args.json_out:
            print(json.dumps(run.as_dict()))
        else:
            _print_run(run, ZoneInfo(schedule.tz), with_schedule=False)
            if run.reply:
                print()
                print(run.reply)
        return 0 if run.outcome in ("ok", "quiet") else 1
    raise AssertionError(cmd)


def _runners(state: Path) -> dict:
    return {"direct": DirectRunner(state / "work")}


# -- serve -------------------------------------------------------------------


def _pid_file(state: Path) -> Path:
    return state / "serve.pid"


def _serving(state: Path) -> bool:
    try:
        pid = int(_pid_file(state).read_text().strip())
        os.kill(pid, 0)
        return True
    except (OSError, ValueError):
        return False


def _serve(store: Store, state: Path) -> int:
    if _serving(state):
        print(f"error: samay serve is already running for {state}",
              file=sys.stderr)
        return 2
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    _pid_file(state).write_text(str(os.getpid()))

    def log(schedule: Schedule, run: Run) -> None:
        _print_run(run, ZoneInfo(schedule.tz), with_schedule=True)
        sys.stdout.flush()

    def started(interrupted: int) -> None:
        active = store.schedules(state="active")
        print(f"samay {__version__}: {len(active)} active schedule(s), "
              f"state in {state}")
        if interrupted:
            print(f"{interrupted} run(s) were going when Samay last stopped; "
                  "marked interrupted, not run again")
        sys.stdout.flush()

    clock = Clock(store, _runners(state), on_record=log)
    try:
        clock.serve(stop, on_start=started)
    finally:
        clock.close()
        _pid_file(state).unlink(missing_ok=True)
    print("stopped")
    return 0


# -- printing ----------------------------------------------------------------


def _card(schedule: Schedule, store: Store | None = None) -> dict:
    card = schedule.as_dict()
    card["sentence"] = schedules.sentence(schedule)
    if store is not None:
        last = store.runs(schedule.id, limit=1)
        card["last_run"] = last[0].as_dict() if last else None
    return card


def _short(moment: str | None, zone: ZoneInfo | None) -> str:
    when = from_iso(moment)
    if when is None:
        return "-"
    return f"{when.astimezone(zone) if zone else when:%a %-d %b %H:%M}"


def _print_schedule(schedule: Schedule, store: Store, full: bool = False) -> None:
    zone = ZoneInfo(schedule.tz)
    print(f"{schedule.id}  {schedule.state:<7} {schedules.sentence(schedule)}")
    print(f"          {schedule.prompt if full else _clip(schedule.prompt, 70)}")
    if schedule.paused_because:
        print(f"          paused: {schedule.paused_because}")
    last = store.runs(schedule.id, limit=1)
    if last:
        run = last[0]
        print(f"          last: {run.outcome}  {_short(run.started_at, zone)}"
              + (f"  {_clip(run.summary, 60)!r}" if run.summary else ""))
    if full:
        print(f"          notify: {schedule.notify}   runner: {schedule.runner}"
              f"   time limit: {schedule.time_limit}s")
        if schedule.agent:
            print(f"          agent: {schedule.agent}")
        if schedule.allow_tools:
            print(f"          allowed: {', '.join(schedule.allow_tools)}")
        if schedule.browser_profile:
            print(f"          browser profile: {schedule.browser_profile}")
        print(f"          made {_short(schedule.created_at, zone)} "
              f"(by {schedule.created_via}), for {schedule.owner}")


def _print_run(run: Run, zone: ZoneInfo | None, with_schedule: bool) -> None:
    head = f"{run.schedule}  " if with_schedule else ""
    cost = f"  ${run.cost_usd:.4f}" if run.cost_usd else ""
    sent = "  sent" if run.notified else ""
    print(f"{head}{_short(run.due_at, zone)}  {run.outcome:<12}"
          f"{cost}{sent}  {_clip(run.summary, 70)}".rstrip())
    for need in run.needs:
        print(f"{' ' * len(head)}    needs: {need}")
    if run.refused:
        print(f"{' ' * len(head)}    not allowed: {', '.join(run.refused)} "
              "(allow with --allow-tools when adding)")


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
