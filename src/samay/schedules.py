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
from datetime import datetime, timedelta
from pathlib import Path

from samay import when as when_mod
from samay.dvara import Dvara, DvaraError
from samay.store import NOTIFY, RUNNERS, Schedule, Store, from_iso, iso, now_utc

DEFAULT_MAX_SCHEDULES = 20
MIN_TIME_LIMIT, MAX_TIME_LIMIT = 30, 3600
DEFAULT_TIME_LIMIT = 600
LOCAL_OWNER = "local"


class ScheduleError(ValueError):
    """A request that cannot become (or change) a schedule, in words."""


def default_tz() -> str:
    """``$SAMAY_TZ``, else this machine's zone, else UTC."""
    configured = os.environ.get("SAMAY_TZ", "").strip()
    if configured:
        return configured
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


def create(store: Store, *, prompt: str, when: dict | str,
           owner: str = LOCAL_OWNER, tz: str | None = None,
           runner: str = "direct", agent: str = "",
           notify: str = "when_new", allow_tools: list[str] | None = None,
           time_limit: int = DEFAULT_TIME_LIMIT, browser_profile: str = "",
           created_via: str = "cli", now: datetime | None = None,
           dvara: Dvara | None = None) -> Schedule:
    now = now or now_utc()
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
    said = preview(when, tz, now)
    mine = [s for s in store.schedules(owner=owner) if s.state != "done"]
    if len(mine) >= max_schedules():
        raise ScheduleError(
            f"{owner} already has {len(mine)} schedules, the most allowed; "
            "remove one first (samay rm ID)")
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
        allow_tools=[g.strip() for g in allow_tools or [] if g.strip()],
        time_limit=int(time_limit), browser_profile=browser_profile,
        created_at=iso(now), created_via=created_via, next_at=said["next"][0])
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


def card(schedule: Schedule, store: Store | None = None) -> dict:
    """A schedule as JSON for a page, a program or an agent: its fields,
    the sentence, and (given the store) its last run."""
    out = schedule.as_dict()
    out["sentence"] = sentence(schedule)
    # The next day's worth of times (at most 24), for a page that draws
    # the day: what will run, and when.
    out["upcoming"] = []
    if schedule.state == "active":
        now = now_utc()
        parsed = when_mod.parse(schedule.when, schedule.tz)
        horizon = now + timedelta(days=1)
        out["upcoming"] = [iso(t) for t in parsed.upcoming(
            now, 24, anchor=from_iso(schedule.created_at)) if t <= horizon]
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
