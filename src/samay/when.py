"""When a schedule runs: a small form, checked, and said back in words.

A schedule is accepted by a PERSON, so the thing they accept has to be a
sentence -- "every 3 hours, next at 14:00, 17:00, 20:00" -- not a cron
string they would have to decode. And it is usually proposed by a MODEL,
often a small local one, which is unreliable at cron and reliable at
filling in a form. So the form is the contract, and cron is an escape
hatch for people who want it:

    {"every": "3h"}
    {"every": "30m", "between": "09:00-18:00", "days": "mon-fri"}
    {"at": "08:00"}
    {"at": ["08:00", "20:00"], "days": "mon-fri"}
    {"once": "2026-10-06T15:00"}
    {"cron": "0 */2 * * *"}

THE SENTENCE AND THE TIMES COME FROM ONE PLACE. ``describe`` builds the
words and the next few times from the same parsed form ``next_after``
runs on, so what a person accepted and what the clock does cannot say
different things.

UNKNOWN KEYS ARE ERRORS. ``{"evry": "3h"}`` is a schedule that would
otherwise never run, silently; the error names the keys that exist.

A FLOOR UNDER EVERY SCHEDULE. Nothing runs more often than every five
minutes, whichever form asked for it. A misunderstanding ("every minute"
for "every morning") is otherwise a bill, and the floor is checked on
the times themselves, so ``{"at": ["08:00", "08:01"]}`` and a busy cron
line are caught as well as a short ``every``.

TIME ZONES ARE THE SCHEDULE'S. "08:00" means 08:00 where the person is,
through daylight-saving changes; ``every`` counts real hours, so "every
3 hours" stays three hours apart across a clock change. Times go in and
out of this module as aware datetimes, and are stored in UTC.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

#: Nothing runs more often than this, whichever form asked for it.
MIN_GAP = timedelta(minutes=5)

#: What one schedule's form may say. Exactly one of the first four.
KINDS = ("every", "at", "once", "cron")
KEYS = (*KINDS, "between", "days")

DAY_NAMES = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
_DAY_WORDS = {"daily": range(7), "everyday": range(7), "weekdays": range(5),
              "weekends": (5, 6), "weekend": (5, 6)}
_DAY_LABELS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")

#: How far ahead the search for a next time goes before it gives up. A
#: cron line for "29 February, on a Monday" exists; a search that never
#: returns does not get to.
_HORIZON_DAYS = 366 * 8


class WhenError(ValueError):
    """A form that cannot become a schedule, said so a model can fix it."""


@dataclass(frozen=True)
class Cron:
    minutes: frozenset[int]
    hours: frozenset[int]
    doms: frozenset[int]
    months: frozenset[int]
    dows: frozenset[int]          # 0 = Monday, as Python counts
    dom_any: bool
    dow_any: bool
    text: str

    def day_matches(self, d: date) -> bool:
        if d.month not in self.months:
            return False
        dom, dow = d.day in self.doms, d.weekday() in self.dows
        # Cron's own rule: with both restricted, EITHER matching is enough.
        if not self.dom_any and not self.dow_any:
            return dom or dow
        return dom and dow


@dataclass(frozen=True)
class When:
    kind: str
    tz: ZoneInfo
    every: timedelta | None = None
    between: tuple[time, time] | None = None
    days: frozenset[int] = frozenset(range(7))
    at: tuple[time, ...] = ()
    once: datetime | None = None           # aware, in tz
    cron: Cron | None = None
    form: dict = field(default_factory=dict)

    # -- the clock -----------------------------------------------------------

    def next_after(self, after: datetime, anchor: datetime | None = None
                   ) -> datetime | None:
        """The first time strictly after ``after``, in UTC; None when there
        is no next one (a ``once`` that has passed).

        ``anchor`` is where ``every`` counts from -- the schedule's start --
        so a schedule made at 10:17 runs at 13:17, 16:17, ... and keeps
        doing so after a restart, rather than drifting to whenever the
        process happened to wake up.
        """
        after = after.astimezone(UTC)
        if self.kind == "once":
            when = self.once.astimezone(UTC)
            return when if when > after else None
        if self.kind == "every" and self.between is None:
            return self._next_every(after, (anchor or after).astimezone(UTC))
        local = after.astimezone(self.tz)
        for offset in range(_HORIZON_DAYS):
            day = local.date() + timedelta(days=offset)
            for candidate in self._times_on(day):
                if candidate > after:
                    return candidate
        return None

    def _next_every(self, after: datetime, anchor: datetime) -> datetime | None:
        step = self.every
        if anchor > after:
            candidate = anchor
        else:
            candidate = anchor + step * ((after - anchor) // step + 1)
        # Day filter: skip ticks that land on a day not chosen. Bounded by
        # a week's worth of the shortest allowed step.
        for _ in range(int(timedelta(days=8) / MIN_GAP) + 1):
            if candidate.astimezone(self.tz).weekday() in self.days:
                return candidate
            candidate += step
        return None

    def _times_on(self, day: date) -> list[datetime]:
        """Every time this schedule runs on one local ``day``, in UTC."""
        if self.kind == "cron":
            if not self.cron.day_matches(day):
                return []
            clock = [time(h, m) for h in sorted(self.cron.hours)
                     for m in sorted(self.cron.minutes)]
        elif day.weekday() not in self.days:
            return []
        elif self.kind == "at":
            clock = list(self.at)
        else:                                      # every, inside a window
            start, end = self.between
            clock, now = [], datetime.combine(day, start)
            last = datetime.combine(day, end)
            while now <= last:
                clock.append(now.time())
                now += self.every
        return sorted(_utc(day, t, self.tz) for t in clock)

    def upcoming(self, after: datetime, count: int = 3,
                 anchor: datetime | None = None) -> list[datetime]:
        out: list[datetime] = []
        cursor = after
        while len(out) < count:
            nxt = self.next_after(cursor, anchor)
            if nxt is None:
                break
            out.append(nxt)
            cursor = nxt
        return out

    def grace(self) -> timedelta:
        """How late a missed time may still run. Half the step for a
        frequent schedule, at most an hour: a 09:00 check run at 09:40 is
        still useful, the same check run at 15:00 is a different one."""
        if self.kind == "every":
            return min(self.every / 2, timedelta(hours=1))
        return timedelta(hours=1)

    # -- words -----------------------------------------------------------------

    def sentence(self) -> str:
        days = _days_phrase(self.days)
        if self.kind == "every":
            words = f"every {duration_words(self.every)}"
            if self.between:
                words += f", {self.between[0]:%H:%M}–{self.between[1]:%H:%M}"
            return words + (f", {days}" if days else "")
        if self.kind == "at":
            times = _and([f"{t:%H:%M}" for t in self.at])
            return (f"at {times}, {days}" if days else f"every day at {times}")
        if self.kind == "once":
            return f"once, on {self.once:%a %-d %b %Y at %H:%M}"
        return f"on the cron line '{self.cron.text}'"


def parse(form: dict | str, tz: str | ZoneInfo) -> When:
    """Turn a form (or its JSON, or the short text the CLI takes) into a
    When, or raise WhenError saying what to change."""
    zone = _zone(tz)
    if isinstance(form, str):
        form = parse_text(form)
    if not isinstance(form, dict):
        raise WhenError('a schedule\'s "when" is an object, e.g. {"every": "3h"}')
    unknown = sorted(set(form) - set(KEYS))
    if unknown:
        raise WhenError(f"unknown key(s) {', '.join(unknown)} in \"when\"; "
                        f"known: {', '.join(KEYS)}")
    kinds = [k for k in KINDS if form.get(k) not in (None, "", [])]
    if len(kinds) != 1:
        raise WhenError('"when" needs exactly one of every, at, once or cron '
                        f"(got {', '.join(kinds) or 'none'})")
    kind = kinds[0]
    if "between" in form and kind != "every":
        raise WhenError('"between" goes with "every" (a window to repeat in)')
    if "days" in form and kind not in ("every", "at"):
        raise WhenError('"days" goes with "every" or "at"; a cron line '
                        "says its own days")
    days = _days(form.get("days"))
    clean = {kind: form[kind]}
    if "days" in form:
        clean["days"] = form["days"]
    if kind == "every":
        step = _duration(form["every"])
        if step < MIN_GAP:
            raise WhenError(f"every {duration_words(step)} is too often; the "
                            f"shortest is every {duration_words(MIN_GAP)}")
        window = None
        if form.get("between"):
            window = _window(form["between"])
            clean["between"] = form["between"]
        when = When("every", zone, every=step, between=window, days=days,
                    form=clean)
    elif kind == "at":
        raw = form["at"]
        items = raw if isinstance(raw, list) else str(raw).split(",")
        times = tuple(sorted({_clock(str(i)) for i in items}))
        when = When("at", zone, at=times, days=days, form=clean)
    elif kind == "once":
        when = When("once", zone, once=_moment(str(form["once"]), zone),
                    form=clean)
    else:
        when = When("cron", zone, cron=_cron(str(form["cron"])), form=clean)
    _check_floor(when)
    return when


def parse_text(text: str) -> dict:
    """The CLI's short form, into the same dict a model sends.

        every 3h
        every 30m between 09:00-18:00 on mon-fri
        at 08:00,20:00 on weekdays
        once 2026-10-06T15:00
        cron 0 */2 * * *

    A JSON object is taken as it is.
    """
    text = text.strip()
    if text.startswith("{"):
        try:
            return json.loads(text)
        except json.JSONDecodeError as exc:
            raise WhenError(f"not valid JSON: {exc}") from None
    head, _, rest = text.partition(" ")
    head, rest = head.lower(), rest.strip()
    if head == "cron":
        return {"cron": rest}
    if head == "once":
        return {"once": rest}
    if head == "daily" and rest.lower().startswith("at "):
        head, rest = "at", rest[3:].strip()
    if head not in ("every", "at"):
        raise WhenError(f"cannot read {text!r}; start with every, at, once "
                        "or cron (e.g. 'every 3h', 'at 08:00 on mon-fri')")
    form: dict = {}
    match = re.search(r"\s+on\s+(.+)$", rest)
    if match:
        form["days"] = match.group(1).strip()
        rest = rest[:match.start()]
    match = re.search(r"\s+between\s+(\S+)$", rest)
    if match:
        form["between"] = match.group(1)
        rest = rest[:match.start()]
    form[head] = rest.strip()
    return form


def describe(when: When, now: datetime, anchor: datetime | None = None,
             count: int = 3) -> str:
    """The sentence a person accepts: what, and when it next happens."""
    times = when.upcoming(now, count, anchor)
    if not times:
        return f"{when.sentence()} -- no time left to run ({when.tz.key})"
    local = [t.astimezone(when.tz) for t in times]
    shown, day = [], None
    for t in local:
        label = f"{t:%H:%M}" if t.date() == day else f"{t:%a %-d %b %H:%M}"
        day = t.date()
        shown.append(label)
    return f"{when.sentence()} -- next: {', '.join(shown)} ({when.tz.key})"


# -- pieces ----------------------------------------------------------------------


def _zone(tz: str | ZoneInfo) -> ZoneInfo:
    if isinstance(tz, ZoneInfo):
        return tz
    try:
        return ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise WhenError(f"unknown time zone {tz!r}; use a name like "
                        "'America/New_York' or 'Asia/Kolkata'") from None


def _utc(day: date, clock: time, tz: ZoneInfo) -> datetime:
    # Through UTC and back: a wall time skipped by a spring-forward lands
    # on the far side of the gap instead of on a time that never existed.
    return datetime.combine(day, clock, tzinfo=tz).astimezone(UTC)


def _duration(raw) -> timedelta:
    text = str(raw).strip().lower().replace(" ", "")
    words = {"minutes": "m", "minute": "m", "mins": "m", "min": "m",
             "hours": "h", "hour": "h", "hrs": "h", "hr": "h",
             "days": "d", "day": "d"}
    for word, unit in words.items():
        text = text.replace(word, unit)
    parts = re.fullmatch(r"(?:(\d+)d)?(?:(\d+)h)?(?:(\d+)m)?", text)
    if not text or parts is None or not any(parts.groups()):
        raise WhenError(f"cannot read {raw!r} as a length of time; write "
                        "it like 30m, 3h, 1h30m or 1d")
    d, h, m = (int(g or 0) for g in parts.groups())
    return timedelta(days=d, hours=h, minutes=m)


def duration_words(step: timedelta) -> str:
    minutes = int(step.total_seconds() // 60)
    days, rem = divmod(minutes, 24 * 60)
    hours, mins = divmod(rem, 60)
    parts = [(days, "day"), (hours, "hour"), (mins, "minute")]
    words = [f"{n} {unit}{'s' if n != 1 else ''}" for n, unit in parts if n]
    if words == ["1 day"]:
        return "day"
    if words == ["1 hour"]:
        return "hour"
    return " ".join(words)


def _clock(raw: str) -> time:
    text = raw.strip().lower().replace(" ", "").replace(".", "")
    match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?(am|pm)?", text)
    if match:
        hour, minute, half = int(match.group(1)), int(match.group(2) or 0), match.group(3)
        if half:
            if not 1 <= hour <= 12:
                match = None
            else:
                hour = hour % 12 + (12 if half == "pm" else 0)
        elif match.group(2) is None:
            match = None                       # a bare "8" is ambiguous
        if match and 0 <= hour <= 23 and 0 <= minute <= 59:
            return time(hour, minute)
    raise WhenError(f"cannot read {raw!r} as a time of day; write it like "
                    "08:00, 20:30 or 8am")


def _window(raw) -> tuple[time, time]:
    start, sep, end = str(raw).partition("-")
    if not sep:
        raise WhenError(f"\"between\" is a window like 09:00-18:00, got {raw!r}")
    a, b = _clock(start), _clock(end)
    if a >= b:
        raise WhenError(f"\"between\" {raw!r} must start before it ends, within "
                        "one day (overnight windows are not supported)")
    return a, b


def _days(raw) -> frozenset[int]:
    if raw in (None, "", []):
        return frozenset(range(7))
    items = raw if isinstance(raw, list) else re.split(r"[,\s]+", str(raw))
    out: set[int] = set()
    for item in (str(i).strip().lower() for i in items):
        if not item:
            continue
        if item in _DAY_WORDS:
            out.update(_DAY_WORDS[item])
            continue
        first, sep, last = item.partition("-")
        a = _day(first, raw)
        if not sep:
            out.add(a)
            continue
        b = _day(last, raw)
        i = a
        while True:                            # fri-mon wraps the weekend
            out.add(i)
            if i == b:
                break
            i = (i + 1) % 7
    if not out:
        raise WhenError(f"no days in {raw!r}")
    return frozenset(out)


def _day(word: str, raw) -> int:
    key = word[:3]
    if key not in DAY_NAMES:
        raise WhenError(f"cannot read {raw!r} as days; use mon..sun, ranges "
                        "like mon-fri, or weekdays / weekends")
    return DAY_NAMES.index(key)


def _days_phrase(days: frozenset[int]) -> str:
    if len(days) == 7:
        return ""
    if days == frozenset(range(5)):
        return "Mon–Fri"
    if days == frozenset((5, 6)):
        return "weekends"
    ordered = sorted(days)
    if len(ordered) > 2 and ordered == list(range(ordered[0], ordered[-1] + 1)):
        return f"{_DAY_LABELS[ordered[0]]}–{_DAY_LABELS[ordered[-1]]}"
    return "on " + ", ".join(_DAY_LABELS[d] for d in ordered)


def _and(items: list[str]) -> str:
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _moment(raw: str, tz: ZoneInfo) -> datetime:
    try:
        moment = datetime.fromisoformat(raw.strip())
    except ValueError:
        raise WhenError(f"cannot read {raw!r} as a date and time; write it "
                        "like 2026-10-06T15:00") from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=tz)
    return moment.astimezone(tz)


_CRON_FIELDS = (("minute", 0, 59), ("hour", 0, 23), ("day of month", 1, 31),
                ("month", 1, 12), ("day of week", 0, 7))
_CRON_NAMES = {3: {m: i + 1 for i, m in enumerate(
                   ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug",
                    "sep", "oct", "nov", "dec"))},
               4: {d: i for i, d in enumerate(
                   ("sun", "mon", "tue", "wed", "thu", "fri", "sat"))}}


def _cron(text: str) -> Cron:
    parts = text.split()
    if len(parts) != 5:
        raise WhenError(f"a cron line has 5 fields (minute hour day month "
                        f"weekday), got {len(parts)} in {text!r}")
    sets = []
    for index, (part, (name, lo, hi)) in enumerate(zip(parts, _CRON_FIELDS, strict=True)):
        sets.append(_cron_field(part.lower(), index, name, lo, hi, text))
    # Cron counts Sunday as 0 (and 7); Python counts Monday as 0.
    dows = frozenset((d - 1) % 7 for d in sets[4])
    return Cron(minutes=frozenset(sets[0]), hours=frozenset(sets[1]),
                doms=frozenset(sets[2]), months=frozenset(sets[3]), dows=dows,
                dom_any=parts[2] == "*", dow_any=parts[4] == "*", text=text)


def _cron_field(part: str, index: int, name: str, lo: int, hi: int,
                text: str) -> set[int]:
    names = _CRON_NAMES.get(index, {})
    out: set[int] = set()
    for item in part.split(","):
        body, _, step_text = item.partition("/")
        try:
            step = int(step_text) if step_text else 1
            if body == "*":
                a, b = lo, hi
            else:
                first, _, last = body.partition("-")
                a = names.get(first, None)
                a = int(first) if a is None else a
                if last:
                    b = names.get(last, None)
                    b = int(last) if b is None else b
                else:
                    b = hi if step_text else a
        except ValueError:
            raise WhenError(f"cannot read the {name} field {part!r} in "
                            f"{text!r}") from None
        if step < 1 or not (lo <= a <= hi and lo <= b <= hi) or a > b:
            raise WhenError(f"the {name} field {part!r} in {text!r} is out of "
                            f"range ({lo}-{hi})")
        out.update(range(a, b + 1, step))
    return out


def _check_floor(when: When) -> None:
    probe = datetime.now(UTC)
    times = when.upcoming(probe, 12, anchor=probe)
    for earlier, later in zip(times, times[1:], strict=False):
        if later - earlier < MIN_GAP:
            raise WhenError(
                f"{when.sentence()} runs {duration_words(later - earlier)} "
                f"apart at times; the shortest gap is "
                f"{duration_words(MIN_GAP)}")
