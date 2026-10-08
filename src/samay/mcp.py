"""The tools an agent uses to offer "I can do this for you later".

    samay mcp --for mahen [--agent DIR|NAME] [--runner direct|dvara]

An MCP server on stdin/stdout -- newline-delimited JSON-RPC, written by
hand like the client in Yantra -- with seven tools:

    preview_schedule   read    check a 'when'; the sentence and next times
    list_schedules     read    this person's schedules
    schedule_runs      read    what one of them did
    create_schedule    write   save one
    pause_schedule     write
    resume_schedule    write
    delete_schedule    write

THE AGENT PROPOSES, THE PERSON ACCEPTS. Nothing here asks anybody
anything: the three read tools say ``readOnlyHint: true`` and the four
others do not, so a harness that honours the hint (Yantra does) puts
every create, pause, resume and delete in front of the person first --
as a permission card in the browser, a y/N in the terminal, two buttons
on Telegram. What they see is the call's arguments: the prompt, the
``when``, what gets sent and which tools it may use unasked. The
descriptions below tell the model to preview first and say the
sentence, so the card arrives after the person has already read it in
plain words.

ONE PERSON PER SERVER. ``--for`` is fixed when the harness starts the
server; every tool sees and changes only that person's schedules, and
the model has no argument with which to name anybody else. A harness
serving several people starts one server per person (or per turn).

WHAT A SCHEDULE RUNS IS THE AGENT THAT MADE IT. ``--agent`` and
``--runner`` are the harness's to set, not the model's: a schedule made
in a conversation with your mail agent runs your mail agent. Without
``--runner``, a person Dvara knows (anyone but ``local``, with
``SAMAY_DVARA_URL`` set) gets the Dvara road; ``local`` gets the direct
one.

NO RUN-NOW. A run is itself an agent turn, minutes long; started from
inside another turn it would hold that turn up, or run beside it on the
same browser profile. The person has ``samay run-now`` and the page.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, TextIO

from samay import __version__, schedules
from samay.dvara import Dvara
from samay.status import serving
from samay.store import NOTIFY, Store

#: What this server speaks, newest first; the client's choice wins when
#: it is one of these.
VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")

_WHEN = {
    "description": (
        'When to run, as an object with exactly one of: {"every": "3h"} '
        '(30m, 2h, 1d; 5 minutes at the least), {"at": "08:00"} or '
        '{"at": ["08:00", "20:00"]}, {"once": "2026-10-06T15:00"}, '
        '{"cron": "0 */2 * * *"}. "days" ("mon-fri", "weekends", '
        '"sat,sun") narrows every/at; "between": "09:00-18:00" narrows '
        "every. Times are the person's own clock."),
    "type": "object",
}

TOOLS: list[dict] = [
    {"name": "preview_schedule",
     "description": (
         "Check when a schedule would run, BEFORE making it: returns the "
         "schedule in plain words with its next three times. Call this "
         "first and tell the person the sentence; only create the "
         "schedule if they say yes to it."),
     "inputSchema": {"type": "object", "properties": {
         "when": _WHEN,
         "tz": {"type": "string", "description": "IANA zone, e.g. "
                "America/New_York. Leave out for the person's own."}},
         "required": ["when"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "list_schedules",
     "description": "The person's schedules: what each does, when it "
                    "next runs, and how its last run went.",
     "inputSchema": {"type": "object", "properties": {}},
     "annotations": {"readOnlyHint": True}},
    {"name": "schedule_runs",
     "description": "What one schedule did on its recent runs, newest first.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"},
         "limit": {"type": "integer", "minimum": 1, "maximum": 50}},
         "required": ["id"]},
     "annotations": {"readOnlyHint": True}},
    {"name": "create_schedule",
     "description": (
         "Save a schedule, after the person agreed to the sentence "
         "preview_schedule gave. At each time this same agent is given "
         "`prompt` with NOBODY watching, so write it as a complete "
         "instruction to yourself for later -- what to check, and what "
         "is worth telling the person. List in allow_tools the tools it "
         "needs to run without asking (e.g. \"browser_*\"); anything else "
         "that changes something is refused or asked about."),
     "inputSchema": {"type": "object", "properties": {
         "prompt": {"type": "string"},
         "when": _WHEN,
         "notify": {"type": "string", "enum": list(NOTIFY),
                    "description": "when_new (default): tell the person "
                    "only when there is something new. always: every time. "
                    "never: keep it for them to read."},
         "allow_tools": {"type": "array", "items": {"type": "string"}},
         "phone_steps": {"type": "array", "items": {"type": "string"},
                         "description": "Held steps on the person's phone this may do "
                         "without asking, each as \"<word> in <app> when the screen "
                         "shows <text>\" (\"send in Messages when the screen shows "
                         "555-0123\"). Only what the person said; anything else held "
                         "is asked in their chat."},
         "wait": {"type": "integer", "minimum": 1, "maximum": 240,
                  "description": "Minutes a question from a run may wait for the "
                  "person, in all (default 30); then it is refused."},
         "tz": {"type": "string"}},
         "required": ["prompt", "when"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "pause_schedule",
     "description": "Stop a schedule running, keeping it to resume later.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"}}, "required": ["id"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "resume_schedule",
     "description": "Start a paused schedule again, from now.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"}}, "required": ["id"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": False}},
    {"name": "delete_schedule",
     "description": "Remove a schedule and its history, for good.",
     "inputSchema": {"type": "object", "properties": {
         "id": {"type": "string"}}, "required": ["id"]},
     "annotations": {"readOnlyHint": False, "destructiveHint": True}},
]


class ToolFailed(Exception):
    """A call the model can read about and fix."""


class Tools:
    def __init__(self, store: Store, state: Path, *, person: str,
                 agent: str = "", runner: str | None = None,
                 dvara: Dvara | None = None, phone: bool = False) -> None:
        self.store = store
        #: This turn has the person's phone (``--phone``, from Dvara): a
        #: schedule made here works it too.
        self.phone = phone
        self.state = state
        self.person = person
        self.agent = agent
        self.dvara = dvara
        if runner is None:
            runner = ("dvara" if dvara is not None
                      and person != schedules.LOCAL_OWNER else "direct")
        self.runner = runner

    def call(self, name: str, args: dict) -> str:
        handler: Callable[[dict], str] | None = getattr(self, f"_{name}", None)
        if handler is None or name not in {t["name"] for t in TOOLS}:
            raise ToolFailed(f"no tool {name!r}")
        try:
            return handler(args)
        except schedules.ScheduleError as exc:
            raise ToolFailed(str(exc)) from None

    def _preview_schedule(self, args: dict) -> str:
        said = schedules.preview(_need(args, "when"), args.get("tz"))
        return said["sentence"]

    def _list_schedules(self, args: dict) -> str:
        mine = self.store.schedules(owner=self.person)
        if not mine:
            return "No schedules yet."
        lines = []
        for schedule in mine:
            card = schedules.card(schedule, self.store)
            last = card["last_run"]
            lines.append(
                f"{schedule.id} [{schedule.state}] {card['sentence']}\n"
                f"  does: {schedule.prompt}\n"
                + (f"  paused: {schedule.paused_because}\n"
                   if schedule.paused_because else "")
                + (f"  last run: {last['outcome']} -- {last['summary']}"
                   if last else "  not run yet"))
        return "\n".join(lines)

    def _schedule_runs(self, args: dict) -> str:
        schedule = self._mine(args)
        limit = max(1, min(int(args.get("limit") or 5), 50))
        runs = self.store.runs(schedule.id, limit=limit)
        if not runs:
            return f"{schedule.id} has not run yet."
        return "\n".join(
            f"{r.due_at} {r.outcome}: {r.summary or r.detail}"
            + (f" (needs: {'; '.join(r.needs)})" if r.needs else "")
            for r in runs)

    def _create_schedule(self, args: dict) -> str:
        allow = args.get("allow_tools") or []
        if not isinstance(allow, list):
            raise ToolFailed("allow_tools is a list of tool names or globs")
        steps = args.get("phone_steps") or []
        if not isinstance(steps, list):
            raise ToolFailed("phone_steps is a list of sentences")
        made = schedules.create(
            self.store, prompt=str(args.get("prompt") or ""),
            when=_need(args, "when"), tz=args.get("tz") or None,
            owner=self.person, runner=self.runner, agent=self.agent,
            notify=str(args.get("notify") or "when_new"),
            allow_tools=[str(g) for g in allow], created_via="agent",
            dvara=self.dvara if self.runner == "dvara" else None,
            phone=self.phone, phone_steps=[str(s) for s in steps],
            wait=_minutes(args.get("wait")))
        said = f"Saved {made.id}: {schedules.sentence(made)}."
        if serving(self.state) is None:
            said += (" Note: Samay's clock is not running on this machine, "
                     "so it will not run on time until `samay serve` is "
                     "started -- tell the person.")
        return said

    def _pause_schedule(self, args: dict) -> str:
        schedule = schedules.pause(self.store, self._mine(args).id)
        return f"Paused {schedule.id}."

    def _resume_schedule(self, args: dict) -> str:
        schedule = schedules.resume(self.store, self._mine(args).id)
        return f"Resumed {schedule.id}: {schedules.sentence(schedule)}."

    def _delete_schedule(self, args: dict) -> str:
        schedule = schedules.remove(self.store, self._mine(args).id)
        return f"Deleted {schedule.id} ({schedule.prompt[:60]})."

    def _mine(self, args: dict):
        return schedules.find(self.store, str(_need(args, "id")),
                              owner=self.person)


def _need(args: dict, key: str):
    value = args.get(key)
    if value in (None, "", {}):
        raise ToolFailed(f"missing: {key}")
    return value


def answer(tools: Tools, message: dict) -> dict | None:
    """One JSON-RPC message in, its reply out (None for a notification)."""
    method, ident = message.get("method"), message.get("id")
    if ident is None:
        return None                    # notifications/initialized and kin
    if method == "initialize":
        asked = (message.get("params") or {}).get("protocolVersion")
        return _ok(ident, {
            "protocolVersion": asked if asked in VERSIONS else VERSIONS[0],
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "samay", "version": __version__},
            "instructions": (
                "Schedules for this person: preview first, say the "
                "sentence, create only after they agree.")})
    if method == "ping":
        return _ok(ident, {})
    if method == "tools/list":
        return _ok(ident, {"tools": TOOLS})
    if method == "tools/call":
        params = message.get("params") or {}
        try:
            text = tools.call(str(params.get("name")),
                              params.get("arguments") or {})
            return _ok(ident, {"content": [{"type": "text", "text": text}],
                               "isError": False})
        except ToolFailed as exc:
            return _ok(ident, {"content": [{"type": "text", "text": str(exc)}],
                               "isError": True})
    return {"jsonrpc": "2.0", "id": ident,
            "error": {"code": -32601, "message": f"no method {method!r}"}}


def _ok(ident: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": ident, "result": result}


def serve(tools: Tools, stdin: TextIO = sys.stdin,
          stdout: TextIO = sys.stdout) -> None:
    """Read one message per line until stdin closes."""
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None,
                     "error": {"code": -32700, "message": "not JSON"}}
        else:
            reply = answer(tools, message) if isinstance(message, dict) else None
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()


def _minutes(value) -> int:
    if value in (None, ""):
        return schedules.DEFAULT_WAIT
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ToolFailed(f"wait is minutes, not {value!r}") from None
