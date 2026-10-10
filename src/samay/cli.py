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
    samay serve [--port 8780]                   the clock, and its page, until stopped
    samay mcp --for WHO [--agent A]             the tools an agent uses (MCP, stdio)
    samay status [--json]                       is the clock running, and where
    samay unit [--install]                      keep the clock running (systemd)

``--when`` takes the short form (``every 30m between 09:00-18:00 on
mon-fri``, ``at 08:00,20:00``, ``once 2026-10-06T15:00``, ``cron 0 */2 *
* *``) or the same thing as JSON (``{"every": "3h"}``) -- which is what
an agent sends.

``samay serve`` has to be running for anything to run on time; it also
serves the page (http.py) at the address it prints. The other commands
only read and change the file, so they work whether it is running or
not, and it notices a new schedule within half a minute.

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

from samay import __version__, mcp, schedules
from samay.clock import Clock
from samay.dvara import Dvara, DvaraError, DvaraNotifier, DvaraRunner
from samay.http import DEFAULT_PORT, Api, SamayServer, serve_token
from samay.runners import DirectRunner
from samay.status import hold_clock, report, samay_command, serving
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
    p.add_argument("--agent", default="", metavar="DIR|NAME",
                   help="the agent package to run (default: plain Yantra); "
                        "on the Dvara road, an agent's name on its roster")
    p.add_argument("--runner", choices=("direct", "dvara"), default="direct",
                   help="run it here (default), or through Dvara as a person "
                        "-- their allowance, their rules, their Telegram")
    p.add_argument("--as", dest="as_actor", default="", metavar="ACTOR",
                   help="the Dvara-road person this runs as and is sent to "
                        "(default: $SAMAY_DVARA_ACTOR)")
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
    p.add_argument("--phone", action="store_true",
                   help="it works the person's phone (the Dvara road): Dvara "
                        "checks the phone is free, then gives the run its tools")
    p.add_argument("--phone-step", action="append", default=[], metavar="SENTENCE",
                   dest="phone_steps",
                   help="a held step on the phone it may do without asking "
                        "(repeatable), e.g. 'send in Messages when the screen "
                        "shows 555-0123'; the Dvara road")
    p.add_argument("--wait", type=int, default=schedules.DEFAULT_WAIT,
                   metavar="MINUTES",
                   help="how long its questions may wait for the person, in "
                        f"all (default {schedules.DEFAULT_WAIT})")
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

    p = sub.add_parser("serve", help="the clock, and its page: run what is "
                                     "due, until stopped")
    p.add_argument("--host", default="127.0.0.1",
                   help="localhost by default; reaching the network is a "
                        "decision, not a default")
    p.add_argument("--port", type=int, default=DEFAULT_PORT,
                   help=f"the page and its API (default {DEFAULT_PORT}; 0 for "
                        "no page)")
    p.add_argument("--public-url", default=None, metavar="URL",
                   help="where a browser reaches the page, when that is not "
                        "where it is bound -- a container's port mapping or a "
                        "proxy (also $SAMAY_PUBLIC_URL)")

    p = sub.add_parser("mcp", help="the tools an agent uses to make "
                                   "schedules, for one person (stdio)")
    p.add_argument("--for", dest="person", required=True, metavar="WHO",
                   help="whose schedules: 'local' here, or a person on "
                        "Dvara's actors file")
    p.add_argument("--agent", default="", metavar="DIR|NAME",
                   help="the agent a schedule made here runs")
    p.add_argument("--runner", choices=("direct", "dvara"), default=None,
                   help="default: dvara for a Dvara person, direct for local")
    p.add_argument("--phone", action="store_true",
                   help="this turn has the person's phone: a schedule made "
                        "here works it too (Dvara passes it)")

    p = sub.add_parser("unit", help="a systemd user unit that keeps samay "
                                    "serve running; prints it, or --install")
    p.add_argument("--install", action="store_true",
                   help="write it, and an env file with this shell's SAMAY_* "
                        "and YANTRA_* settings (it starts nothing)")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)

    p = sub.add_parser("status", help="is the clock running, and where")
    p.add_argument("--json", action="store_true", dest="json_out")
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
            time_limit=args.time_limit, browser_profile=args.browser_profile,
            runner=args.runner, owner=args.as_actor or schedules.LOCAL_OWNER,
            dvara=_dvara() if args.runner == "dvara" else None,
            phone=args.phone or bool(args.phone_steps),
            phone_steps=args.phone_steps, wait=args.wait)
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
        return _serve(store, state, host=args.host, port=args.port,
                      public_url=args.public_url)
    if cmd == "mcp":
        tools = mcp.Tools(store, state, person=args.person, agent=args.agent,
                          runner=args.runner, dvara=_dvara(), phone=args.phone)
        mcp.serve(tools)
        return 0
    if cmd == "unit":
        from samay import unit
        command = samay_command()
        if not args.install:
            print(unit.unit_text(command, state.resolve(), args.port), end="")
            return 0
        written, env, names = unit.install(command, state.resolve(), args.port,
                                           dict(os.environ))
        print(f"wrote {written}")
        print(f"wrote {env} (yours alone): PATH"
              + (", " + ", ".join(names) if names else ""))
        if not os.environ.get("SAMAY_YANTRA"):
            print("note: SAMAY_YANTRA is not set here, so the service will look for "
                  "`yantra` on PATH")
        print("nothing is started; to start it now and at every login:")
        for line in unit.NEXT:
            print(f"  {line}")
        return 0
    if cmd == "status":
        said = report(state, store)
        if args.json_out:
            print(json.dumps(said))
        else:
            counts = said["schedules"]
            print(f"samay {said['version']}: "
                  + (f"serving at {said['url']}" if said["serving"]
                     else "the clock is not running (samay serve)"))
            print(f"  {counts['active']} active, {counts['paused']} paused, "
                  f"{counts['done']} done; state in {said['state']}")
            print("  answers go to " + (said["dvara"] or "nobody (no Dvara set)"))
        return 0

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
        clock = Clock(store, _runners(state), notifier=_notifier())
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


def _dvara() -> Dvara | None:
    try:
        return Dvara.from_env()
    except DvaraError as exc:
        raise schedules.ScheduleError(str(exc)) from None


def _runners(state: Path) -> dict:
    runners: dict = {"direct": DirectRunner(state / "work")}
    dvara = _dvara()
    if dvara is not None:
        runners["dvara"] = DvaraRunner(dvara)
    return runners


def _notifier() -> DvaraNotifier | None:
    """Where answers go: the person's channels through Dvara, when there
    is a Dvara; otherwise nowhere, and the runs are only kept."""
    dvara = _dvara()
    return DvaraNotifier(dvara) if dvara is not None else None


# -- serve -------------------------------------------------------------------


def _serve_file(state: Path) -> Path:
    return state / "serve.json"


def _serving(state: Path) -> bool:
    return serving(state) is not None


def _serve(store: Store, state: Path, *, host: str, port: int,
           public_url: str | None = None) -> int:
    held = hold_clock(state)       # kept open (and so held) until this process ends
    if held is None:
        print(f"error: samay serve is already running for {state}",
              file=sys.stderr)
        return 2
    clock = None
    server = None
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    def log(schedule: Schedule, run: Run) -> None:
        _print_run(run, ZoneInfo(schedule.tz), with_schedule=True)
        sys.stdout.flush()

    def started(interrupted: int) -> None:
        active = store.schedules(state="active")
        dvara = _dvara()
        print(f"samay {__version__}: {len(active)} active schedule(s), "
              f"state in {state}")
        if server is not None:
            print(f"page: {server.page_url}")
        print(f"answers go to: {dvara.url} (/notify)" if dvara else
              "answers go nowhere: set SAMAY_DVARA_URL to send them to "
              "people's channels; until then they are only kept")
        if interrupted:
            print(f"{interrupted} run(s) were going when Samay last stopped; "
                  "marked interrupted, not run again")
        sys.stdout.flush()

    clock = Clock(store, _runners(state), notifier=_notifier(), on_record=log)
    if port:
        try:
            server = SamayServer(Api(store, clock, state, _dvara()),
                                 serve_token(state), host=host, port=port,
                                 public_url=public_url)
        except (OSError, ValueError) as exc:
            clock.close()
            print(f"error: cannot serve the page on {host}:{port}: {exc}",
                  file=sys.stderr)
            return 2
        server.start()
    told = _dvara()
    # where answers go, for a harness asking `samay status` from a process
    # that doesn't have this one's environment (Yantra's page)
    _serve_file(state).write_text(json.dumps(
        {"pid": os.getpid(), "url": server.url if server else None,
         "dvara": told.url if told else None,
         "local_to": told.actor if told else ""}))
    try:
        clock.serve(stop, on_start=started)
    finally:
        if server is not None:
            server.stop()
        clock.close()
        _serve_file(state).unlink(missing_ok=True)
    print("stopped")
    return 0


# -- printing ----------------------------------------------------------------


def _card(schedule: Schedule, store: Store | None = None) -> dict:
    return schedules.card(schedule, store)


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
        if schedule.phone:
            print("          works your phone")
        for step in schedule.phone_steps:
            print(f"          on the phone, unasked: {step}")
        if schedule.runner == "dvara":
            print(f"          questions wait: {schedule.wait} min")
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
    # A refusal with its words after the name was a question nobody
    # answered in the schedule's wait (Dvara); a bare name was not allowed.
    asked = [r for r in run.refused if ": " in r]
    refused = [r for r in run.refused if ": " not in r]
    for line in asked:
        print(f"{' ' * len(head)}    asked, not answered: {line}")
    if refused:
        print(f"{' ' * len(head)}    not allowed: {', '.join(refused)} "
              "(allow with --allow-tools when adding)")


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


if __name__ == "__main__":
    raise SystemExit(main())
