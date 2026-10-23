"""Making, pausing, resuming and removing schedules -- one place for all.

The CLI calls these, and so will the HTTP surface and the tools an agent
gets, so the rules hold however a schedule arrives: the ``when`` form is
checked and said back in words, the first time is worked out now, and a
person cannot quietly pile up schedules.

A CAP PER PERSON. Twenty schedules by default (``SAMAY_MAX_SCHEDULES``).
Each one spends a model call every time it runs, and an agent that
misread a request ten times is ten schedules nobody asked for.

A TIME LIMIT WITH BOUNDS. Every run has one; between thirty seconds and
an hour. A run that needs longer than an hour is not a check, it is a
job, and wants a different tool.

RESUMING STARTS FROM NOW. A schedule paused for a week does not come
back owing the week: its next time is worked out from the moment it is
resumed, and its count of failures starts again.
"""

from __future__ import annotations

import os
import re
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from samay import when as when_mod
from samay.dvara import Dvara, DvaraError
from samay.store import NOTIFY, RUNNERS, Schedule, Store, from_iso, iso, now_utc

DEFAULT_MAX_SCHEDULES = 20
MIN_TIME_LIMIT, MAX_TIME_LIMIT = 30, 3600
DEFAULT_TIME_LIMIT = 600
#: Minutes a scheduled run's questions may wait for the person, in all.
MIN_WAIT, MAX_WAIT, DEFAULT_WAIT = 1, 240, 30
#: "<word> in <app> when the screen shows <text>" -- the form Sparsh reads
#: (its rules.py); checked here too, so a schedule never saves a grant
#: the phone would refuse to read.
PHONE_STEP = re.compile(
    r"^\s*\S.*?\s+in\s+\S.*?\s+when the screen shows\s+\S.*$", re.IGNORECASE)
LOCAL_OWNER = "local"
#: A tool the run may use unasked: a name or glob, maybe narrowed to fixed
#: argument values -- ``call_service(domain=switch, entity_id=switch.lights_2)``.
#: Yantra reads the form (its ``Grant``); checked here too, so a schedule
#: never saves one that would be refused at its time.
_VALUE = r'(?:"[^"]*"|[^,"()]*)'
_PAIR = rf"\s*[A-Za-z_][A-Za-z0-9_.-]*\s*=\s*{_VALUE}\s*"
GRANT = re.compile(rf"^[^\s()]+(?:\({_PAIR}(?:,{_PAIR})*\))?$")


class ScheduleError(ValueError):
    """A request that cannot become (or change) a schedule, in words."""


def default_tz() -> str:
    """``$SAMAY_TZ``, else ``$TZ`` when it names a zone, else this
    machine's zone, else UTC.

    $TZ BEFORE /etc/localtime. A container's /etc/localtime is usually
    UTC whatever the person's clock says; Sarathi hands each container
    the person's zone as $TZ instead. Read only /etc/localtime, a
    schedule made there "at 08:00" ran at 4 am in New York."""
    configured = os.environ.get("SAMAY_TZ", "").strip()
    if configured:
        return configured
    named = os.environ.get("TZ", "").strip().removeprefix(":")
    if named and "/" in named:  # a zone's name, not a POSIX rule like EST5EDT
        try:
            ZoneInfo(named)
            return named
        except (ZoneInfoNotFoundError, ValueError):
            pass
    try:
        target = os.path.realpath("/etc/localtime")
        marker = "/zoneinfo/"
        if marker in target:
            return target.split(marker, 1)[1]
    except OSError:
        pass
    return "UTC"


def max_schedules() -> int:
    raw = os.environ.get("SAMAY_MAX_SCHEDULES", "").strip()
    try:
        return int(raw) if raw else DEFAULT_MAX_SCHEDULES
    except ValueError:
        raise ScheduleError(
            f"SAMAY_MAX_SCHEDULES must be a whole number, got {raw!r}") from None


def preview(form: dict | str, tz: str | None = None,
            now: datetime | None = None) -> dict:
    """Check a ``when`` and say it back -- what a person is asked to
    accept, before anything is saved."""
    now = now or now_utc()
    try:
        parsed = when_mod.parse(form, tz or default_tz())
    except when_mod.WhenError as exc:
        raise ScheduleError(str(exc)) from None
    times = parsed.upcoming(now, 3, anchor=now)
    if not times:
        raise ScheduleError(f"{parsed.sentence()} has no time left to run")
    return {"when": parsed.form, "tz": parsed.tz.key,
            "sentence": when_mod.describe(parsed, now, anchor=now),
            "next": [iso(t) for t in times]}


#: A phone's name, as Sparsh takes it (its phones.py).
PHONE_NAME = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")

def create(store: Store, *, prompt: str, when: dict | str,
           owner: str = LOCAL_OWNER, tz: str | None = None,
           runner: str = "direct", agent: str = "",
           notify: str = "when_new", allow_tools: list[str] | None = None,
           time_limit: int = DEFAULT_TIME_LIMIT, browser_profile: str = "",
           created_via: str = "cli", now: datetime | None = None,
           dvara: Dvara | None = None, phone: bool | str = False,
           phone_steps: list[str] | None = None,
           wait: int = DEFAULT_WAIT) -> Schedule:
    """``phone``: true, or the name of one of the person's phones
    ("nexus") -- which Dvara checks is free and gives the run alone."""
    now = now or now_utc()
    phone_name = phone.strip() if isinstance(phone, str) else ""
    if isinstance(phone, str) and not PHONE_NAME.fullmatch(phone_name):
        raise ScheduleError(f"{phone!r} can't name a phone: lower case letters, digits "
                            "and dashes, as Sparsh names it (nexus, asha-iphone)")
    prompt = (prompt or "").strip()
    if not prompt:
        raise ScheduleError("a schedule needs a prompt: what to do each time")
    if notify not in NOTIFY:
        raise ScheduleError(f"notify must be one of {', '.join(NOTIFY)}, "
                            f"got {notify!r}")
    if runner not in RUNNERS:
        raise ScheduleError(f"runner must be one of {', '.join(RUNNERS)}, "
                            f"got {runner!r}")
    if not MIN_TIME_LIMIT <= int(time_limit) <= MAX_TIME_LIMIT:
        raise ScheduleError(f"time limit must be between {MIN_TIME_LIMIT} "
                            f"and {MAX_TIME_LIMIT} seconds, got {time_limit}")
    steps = [s.strip() for s in phone_steps or [] if s.strip()]
    for step in steps:
        if not PHONE_STEP.match(step):
            raise ScheduleError(
                f"{step!r} is not a step on the phone: say <word> in <app> when "
                'the screen shows <text> ("send in Messages when the screen '
                'shows 555-0123")')
    grants = check_grants(allow_tools)
    if steps and runner != "dvara":
        raise ScheduleError("steps on the phone the person allowed ahead of time are "
                            "for the Dvara road, where its grants are kept")
    # A PHONE TOOL WITHOUT THE PHONE IS A PROMISE IT CAN'T KEEP. A direct
    # run gets the phone only when the schedule says it works it (``phone``,
    # made in a turn that had the phone and a Dvara to ask through). One
    # that merely granted Sparsh's tools woke up without them: made on
    # Yantra's page, it read the battery from Home Assistant instead, every
    # morning. Refused now, with where to ask.
    if not phone and runner != "dvara" and any(g.startswith("mcp__sparsh__")
                                               for g in grants):
        raise ScheduleError(
            "a schedule that works the phone says so (phone: true), in a chat that "
            "has the phone and a Dvara to ask through -- Yantra's page with Sarathi, "
            "Telegram, or Sarathi's home page chat; a run nobody can be asked about "
            "gets no phone")
    if steps and not phone:
        raise ScheduleError("steps on the phone are for a schedule that uses the "
                            "phone (phone: true, in a chat that has it; or --phone)")
    if not MIN_WAIT <= int(wait) <= MAX_WAIT:
        raise ScheduleError(f"wait must be between {MIN_WAIT} and {MAX_WAIT} "
                            f"minutes, got {wait}")
    said = preview(when, tz, now)
    mine = [s for s in store.schedules(owner=owner) if s.state != "done"]
    if len(mine) >= max_schedules():
        raise ScheduleError(
            f"{owner} already has {len(mine)} schedules, the most allowed; "
            "remove one first (samay rm ID)")
    if runner == "tests" and (agent or grants or phone or steps or browser_profile):
        raise ScheduleError("a tests schedule asks no agent anything: it replays "
                            "the kept tests, each against its own agent, so it "
                            "takes no agent, tools, phone or browser")
    if runner == "doctor" and (agent or grants or phone or steps or browser_profile):
        raise ScheduleError("a doctor schedule asks no agent anything: it asks "
                            "Sarathi's doctor what's wrong, so it takes no agent, "
                            "tools, phone or browser")
    if runner == "backup" and (agent or grants or phone or steps or browser_profile):
        raise ScheduleError("a backup schedule asks no agent anything: Sarathi makes "
                            "the backup, so it takes no agent, tools, phone or browser")
    if runner == "direct" and agent:
        package = Path(agent).expanduser().resolve()
        if not (package / "agent.toml").is_file():
            raise ScheduleError(f"{agent} is not an agent package (no "
                                "agent.toml in it)")
        agent = str(package)
    if runner == "dvara":
        owner = _dvara_owner(dvara, agent, owner)
        if browser_profile:
            raise ScheduleError("--browser-profile is for the direct road; on "
                                "the Dvara road the browser is Dvara's to set")
    if browser_profile:
        browser_profile = str(Path(browser_profile).expanduser().resolve())
    schedule = Schedule(
        id="", owner=owner, prompt=prompt, when=said["when"], tz=said["tz"],
        runner=runner, agent=agent, notify=notify,
        allow_tools=grants,
        time_limit=int(time_limit), browser_profile=browser_profile,
        created_at=iso(now), created_via=created_via, next_at=said["next"][0],
        phone=bool(phone), phone_name=phone_name, phone_steps=steps, wait=int(wait))
    return store.add(schedule)


def _dvara_owner(dvara: Dvara | None, agent: str, owner: str) -> str:
    """Check a Dvara-road schedule against the Dvara it will run on:
    reachable, the agent on its roster, and a person to run as."""
    if dvara is None:
        raise ScheduleError("the Dvara road needs SAMAY_DVARA_URL and "
                            "SAMAY_DVARA_TOKEN")
    if not agent:
        raise ScheduleError("the Dvara road needs --agent NAME, an agent on "
                            "Dvara's roster")
    try:
        offered = dvara.agents()
    except (DvaraError, TimeoutError) as exc:
        raise ScheduleError(str(exc)) from None
    if agent not in offered:
        raise ScheduleError(f"dvara has no agent {agent!r}; it offers: "
                            f"{', '.join(offered) or 'none'}")
    person = owner if owner != LOCAL_OWNER else dvara.actor
    if not person:
        raise ScheduleError("say who this runs as: --as ACTOR (someone in "
                            "Dvara's actors file), or set SAMAY_DVARA_ACTOR")
    return person


def check_grants(allow_tools: list[str] | None) -> list[str]:
    """The tools a schedule may use unasked, each checked as a grant."""
    grants = [g.strip() for g in allow_tools or [] if g.strip()]
    for grant in grants:
        if not GRANT.match(grant):
            raise ScheduleError(
                f"{grant!r} is not a tool to allow: a tool name ('browser_*'), or "
                "one fixed to what it acts on, 'call_service(domain=switch, "
                "entity_id=switch.lights_2)'")
    return grants


def allow(store: Store, schedule_id: str, allow_tools: list[str],
          owner: str | None = None) -> Schedule:
    """Let a schedule use more tools unasked, from its next run.

    ADDED, NEVER REPLACED. The answer that brings this here is "it was
    refused X; allow X" -- the yes given when the schedule was made
    still stands beside it. Taking a tool away is a new schedule."""
    schedule = find(store, schedule_id, owner)
    grants = check_grants(allow_tools)
    if not grants:
        raise ScheduleError("say which tool to allow")
    merged = list(dict.fromkeys([*schedule.allow_tools, *grants]))
    store.update(schedule.id, allow_tools=merged)
    return store.get(schedule.id)


def find(store: Store, schedule_id: str, owner: str | None = None) -> Schedule:
    """One schedule by id -- or by a unique start of one -- that this
    owner may touch (None: the owner of the service, who may touch all)."""
    schedule = store.get(schedule_id)
    if schedule is None:
        matches = [s for s in store.schedules(owner=owner)
                   if s.id.startswith(schedule_id)] if schedule_id else []
        if len(matches) == 1:
            schedule = matches[0]
    if schedule is None or (owner is not None and schedule.owner != owner):
        raise ScheduleError(f"no schedule {schedule_id!r}")
    return schedule


def pause(store: Store, schedule_id: str, owner: str | None = None,
          because: str = "paused by you") -> Schedule:
    schedule = find(store, schedule_id, owner)
    if schedule.state == "done":
        raise ScheduleError(f"{schedule.id} has finished; there is nothing "
                            "to pause")
    store.update(schedule.id, state="paused", paused_because=because)
    return store.get(schedule.id)


def resume(store: Store, schedule_id: str, owner: str | None = None,
           now: datetime | None = None) -> Schedule:
    now = now or now_utc()
    schedule = find(store, schedule_id, owner)
    parsed = when_mod.parse(schedule.when, schedule.tz)
    nxt = parsed.next_after(now, anchor=from_iso(schedule.created_at))
    if nxt is None:
        raise ScheduleError(f"{schedule.id} has no time left to run; remove "
                            "it, or make a new one")
    store.update(schedule.id, state="active", paused_because="", failures=0,
                 next_at=iso(nxt))
    return store.get(schedule.id)


def remove(store: Store, schedule_id: str, owner: str | None = None) -> Schedule:
    schedule = find(store, schedule_id, owner)
    store.delete(schedule.id)
    return schedule


MAX_AHEAD_DAYS = 14


def card(schedule: Schedule, store: Store | None = None, ahead: int = 1) -> dict:
    """A schedule as JSON for a page, a program or an agent: its fields,
    the sentence, and (given the store) its last run."""
    out = schedule.as_dict()
    out["sentence"] = sentence(schedule)
    # The next ``ahead`` days' worth of times (24 a day at most), for a
    # page that draws the day or the week: what will run, and when.
    out["upcoming"] = []
    if schedule.state == "active":
        ahead = max(1, min(int(ahead), MAX_AHEAD_DAYS))
        now = now_utc()
        parsed = when_mod.parse(schedule.when, schedule.tz)
        horizon = now + timedelta(days=ahead)
        out["upcoming"] = [iso(t) for t in parsed.upcoming(
            now, 24 * ahead, anchor=from_iso(schedule.created_at)) if t <= horizon]
    if store is not None:
        last = store.runs(schedule.id, limit=1)
        out["last_run"] = last[0].as_dict() if last else None
    return out


def sentence(schedule: Schedule, now: datetime | None = None) -> str:
    """The schedule said in words, with its next times when it has any."""
    parsed = when_mod.parse(schedule.when, schedule.tz)
    if schedule.state != "active":
        return parsed.sentence()
    return when_mod.describe(parsed, now or now_utc(),
                             anchor=from_iso(schedule.created_at))
