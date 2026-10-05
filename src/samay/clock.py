"""The clock: wake up, see what is due, hand it over, write it down.

Every rule about TIME lives here, and each one exists because of a way
an unwatched schedule goes wrong:

* A MISSED TIME RUNS ONCE, LATE, OR NOT AT ALL. The machine was asleep
  at 08:00 and wakes at 08:20: the 08:00 check still runs, because it is
  within the schedule's grace (half its step, at most an hour). Waking
  at 14:00, it does not: that would be a different check wearing the
  morning's name. Either way the clock moves on to the next time, and
  however many times were missed while it was down, ONE row says so.
  A backlog is never replayed -- twelve hourly checks fired at once are
  twelve bills for one answer.
* ONE RUN OF A SCHEDULE AT A TIME. If the last run is still going when
  the next time comes, the new time is recorded as ``skipped``.
* THE NEXT TIME IS CLAIMED BEFORE THE RUN STARTS. A crash mid-run must
  not run the same time again on restart (a run spends money, and may
  have done something); it shows up as ``interrupted`` instead.
* TOO MANY FAILURES IN A ROW PAUSE THE SCHEDULE, and the person is told
  once. Three, by default. A schedule that fails every hour all night is
  a night of bills and no answers.
* A RUN THAT NEEDS A PERSON PAUSES AT ONCE. An expired login does not
  fix itself between 09:00 and 10:00, so the 10:00 run would only find
  the same page. The person is told what is needed; resuming is theirs.
* A BUSY BROWSER IS NOT A FAILURE. Another Yantra had the profile; the
  run is ``busy``, nobody is told, and the next time tries again.
* A HELD RUN IS WAITING, NOT FAILED. On the Dvara road a turn may stop
  for the person's approval of a tool; they have been asked on their
  channel already, so the run is ``held`` and nothing more is sent.

WHAT IS SENT, AND WHEN, is the schedule's ``notify``: ``always`` sends
every answer; ``when_new`` asks the agent to reply ``NOTHING NEW`` when
there is nothing worth telling, and sends only the others; ``never``
keeps everything and sends nothing. ``NOTHING NEW`` IS FOR A CHECK THAT
WAS DONE. Offered as a plain escape, a small model took it when a site
showed it a sign-in page -- a failure filed as a quiet success, told to
nobody -- so the instruction says in as many words that a run which
could not do the work must say what stopped it instead. A schedule being paused is always
said, whatever ``notify`` is -- a schedule that quietly stops is worse
than one that never started.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Protocol

from samay import when as when_mod
from samay.runners import Runner, RunResult
from samay.store import (FAILURES, Run, Schedule, Store, from_iso, iso,
                         now_utc)

#: Failures in a row before a schedule pauses itself.
MAX_FAILURES = 3

#: The reply that means "nothing worth telling" under ``when_new``.
QUIET_WORDS = "NOTHING NEW"

#: The longest the clock sleeps, so a schedule added by another process
#: (the CLI) is noticed within this long.
MAX_SLEEP = 30.0

#: Runs going at once, across all schedules.
WORKERS = 4

_QUIET = re.compile(r"^[\W_]*nothing new[\W_]*$", re.IGNORECASE)


class Notifier(Protocol):
    """Somewhere to tell the schedule's owner something. True if sent."""

    def send(self, schedule: Schedule, text: str) -> bool: ...


def compose(schedule: Schedule, last: Run | None) -> str:
    """The prompt a run is given: the schedule's own, with what the agent
    should know about this run around it."""
    parsed = when_mod.parse(schedule.when, schedule.tz)
    told = {"always": "your answer is sent to the person",
            "when_new": "your answer is sent to the person only if there "
                        "is something new",
            "never": "your answer is kept for the person to read later"}
    parts = [f"(A scheduled run -- {parsed.sentence()}. Nobody is watching "
             f"right now; {told[schedule.notify]}.)", "", schedule.prompt]
    if last is not None and last.summary:
        when = from_iso(last.started_at).astimezone(parsed.tz)
        parts += ["", f"(Last run, {when:%a %-d %b %H:%M}: {last.summary})"]
    if schedule.notify == "when_new":
        parts += ["", "If you did what was asked and there is nothing new "
                      "worth telling the person since the last run, reply with "
                      f"exactly: {QUIET_WORDS}. If you could NOT do it -- a "
                      "page asked you to sign in, something failed, a tool was "
                      f"refused -- never reply {QUIET_WORDS}; say what stopped "
                      "you."]
    return "\n".join(parts)


def summarize(text: str, limit: int = 200) -> str:
    """The first line worth reading, short enough for a list. A line that
    only introduces what follows ("Here are the top 3 stories:") says
    nothing alone, so it takes the next line with it."""
    lines = [ln.strip().strip("#*_> ").strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return ""
    line = lines[0]
    if line.endswith(":") and len(lines) > 1:
        line = f"{line} {lines[1]}"
    return line if len(line) <= limit else line[:limit - 1] + "…"


def is_quiet(text: str) -> bool:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return bool(lines) and bool(_QUIET.match(lines[0].strip()))


class Clock:
    def __init__(self, store: Store, runners: dict[str, Runner], *,
                 notifier: Notifier | None = None,
                 now: Callable[[], datetime] = now_utc,
                 workers: int = WORKERS,
                 on_record: Callable[[Schedule, Run], None] | None = None
                 ) -> None:
        self.store = store
        self.runners = runners
        self.notifier = notifier
        #: Told about every run written down, missed ones included --
        #: what ``samay serve`` prints as its log.
        self.on_record = on_record
        self.now = now
        self._pool = ThreadPoolExecutor(max_workers=workers,
                                        thread_name_prefix="samay-run")
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def close(self) -> None:
        self._pool.shutdown(wait=True)

    # -- the loop ----------------------------------------------------------

    def serve(self, stop: threading.Event,
              on_start: Callable[[int], None] | None = None) -> None:
        """Tick until ``stop`` is set."""
        interrupted = self.store.interrupt_unfinished(self.now())
        if on_start is not None:
            on_start(interrupted)
        while not stop.is_set():
            self.tick()
            stop.wait(self.sleep_for())

    def sleep_for(self) -> float:
        now = self.now()
        upcoming = [from_iso(s.next_at) for s in self.store.schedules(state="active")
                    if s.next_at]
        if not upcoming:
            return MAX_SLEEP
        return max(0.5, min(MAX_SLEEP, (min(upcoming) - now).total_seconds()))

    def tick(self) -> list[Future]:
        """Deal with everything due now. Returns the runs it started."""
        now = self.now()
        started: list[Future] = []
        for schedule in self.store.schedules(state="active"):
            due = from_iso(schedule.next_at)
            if due is None or due > now:
                continue
            started += self._due(schedule, due, now)
        return started

    def _due(self, schedule: Schedule, due: datetime, now: datetime
             ) -> list[Future]:
        parsed = when_mod.parse(schedule.when, schedule.tz)
        nxt = parsed.next_after(now, anchor=from_iso(schedule.created_at))
        # Claimed first: whatever happens to this run, this time is spent.
        if nxt is None:
            self.store.update(schedule.id, next_at=None, state="done")
        else:
            self.store.update(schedule.id, next_at=iso(nxt))
        late = now - due
        if late > parsed.grace():
            self._mark(schedule, due, "missed",
                       f"due at {_local(due, parsed)}, but Samay was not "
                       f"running then; more than {_words(parsed.grace())} "
                       "late, so it was not run")
            return []
        if self._busy(schedule):
            self._mark(schedule, due, "skipped",
                       "the run before it was still going")
            return []
        return [self._submit(schedule, due)]

    def run_now(self, schedule_id: str) -> Run:
        """Run one schedule at once, here, and wait for it. Its next time
        is left alone: this is an extra run, not the next one early."""
        schedule = self.store.get(schedule_id)
        if schedule is None:
            raise KeyError(schedule_id)
        if self._busy(schedule):
            raise RuntimeError(f"{schedule.id} is running already")
        with self._lock:
            self._running.add(schedule.id)
        return self._execute(schedule, self.now())

    # -- one run -----------------------------------------------------------

    def _busy(self, schedule: Schedule) -> bool:
        with self._lock:
            if schedule.id in self._running:
                return True
        # A run in another process (the CLI's run-now) counts as well, for
        # as long as it could still be going.
        cutoff = self.now() - timedelta(seconds=schedule.time_limit + 120)
        return any(r.outcome == "running" and from_iso(r.started_at) > cutoff
                   for r in self.store.runs(schedule.id, limit=5))

    def _submit(self, schedule: Schedule, due: datetime) -> Future:
        with self._lock:
            self._running.add(schedule.id)
        return self._pool.submit(self._execute, schedule, due)

    def _execute(self, schedule: Schedule, due: datetime) -> Run:
        try:
            run = self.store.start_run(schedule.id, due, at=self.now())
            prompt = compose(schedule, self.store.last_finished(schedule.id))
            runner = self.runners.get(schedule.runner)
            if runner is None:
                result = RunResult(ok=False, stop_reason="error",
                                   detail=f"no {schedule.runner} runner is set "
                                          "up in this Samay")
            else:
                try:
                    result = runner.run(schedule, prompt)
                except Exception as exc:    # a runner's bug is a failed run
                    result = RunResult(ok=False, stop_reason="error",
                                       detail=f"{type(exc).__name__}: {exc}")
            self._record(schedule, run, result)
            return run
        finally:
            with self._lock:
                self._running.discard(schedule.id)

    def _record(self, schedule: Schedule, run: Run, result: RunResult) -> None:
        run.reply = result.text
        run.summary = summarize(result.text) or summarize(result.detail)
        run.cost_usd = result.cost_usd
        run.needs = list(result.needs)
        run.refused = list(result.refused)
        run.detail = result.detail
        run.dvara_run_id = result.dvara_run_id
        if result.timed_out:
            run.outcome = "timed_out"
        elif result.needs:
            run.outcome = "needs_person"
        elif result.held:
            run.outcome = "held"
        elif result.busy:
            run.outcome = "busy"
            run.detail = "; ".join(result.busy)
        elif not result.ok:
            run.outcome = "failed"
        elif schedule.notify == "when_new" and is_quiet(result.text):
            run.outcome = "quiet"
        else:
            run.outcome = "ok"

        # Re-read: the person may have paused or removed it while it ran.
        current = self.store.get(schedule.id)
        paused_because = ""
        if current is not None:
            failures = current.failures
            if run.outcome in FAILURES:
                failures += 1
            elif run.outcome in ("ok", "quiet"):
                failures = 0
            changes: dict = {"failures": failures}
            if current.state == "active":
                if run.outcome == "needs_person":
                    paused_because = "needs you: " + "; ".join(run.needs)
                elif failures >= MAX_FAILURES:
                    paused_because = (f"failed {failures} times in a row; last: "
                                      f"{run.detail or run.outcome}")
                if paused_because:
                    changes.update(state="paused", paused_because=paused_because)
            self.store.update(schedule.id, **changes)

        if run.outcome == "ok" and schedule.notify != "never":
            run.notified = self._send(schedule, result.text)
        if paused_because:
            sent = self._send(schedule, (
                f"Paused: {summarize(schedule.prompt, 80)}\n"
                f"{paused_because}\n"
                f"Resume it with: samay resume {schedule.id}"))
            run.notified = run.notified or sent
        self.store.finish_run(run, at=self.now())
        self._told(schedule, run)

    def _send(self, schedule: Schedule, text: str) -> bool:
        if self.notifier is None or not text.strip():
            return False
        try:
            return bool(self.notifier.send(schedule, text))
        except Exception:
            return False         # the run happened; telling about it did not

    def _mark(self, schedule: Schedule, due: datetime, outcome: str,
              detail: str) -> None:
        run = self.store.start_run(schedule.id, due, outcome=outcome,
                                   at=self.now())
        run.detail = detail
        run.summary = detail
        self.store.finish_run(run, at=self.now())
        self._told(schedule, run)

    def _told(self, schedule: Schedule, run: Run) -> None:
        if self.on_record is not None:
            try:
                self.on_record(schedule, run)
            except Exception:
                pass             # a log line is never worth a lost run


def _local(moment: datetime, parsed: when_mod.When) -> str:
    return f"{moment.astimezone(parsed.tz):%a %-d %b %H:%M}"


def _words(step: timedelta) -> str:
    return when_mod.duration_words(step)
