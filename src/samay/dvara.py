"""The Dvara road: a scheduled turn run AS the person, through Dvara.

The direct road (runners.py) starts Yantra on this machine with nobody
attached. That is enough to do the work and write it down, and nothing
more: it has no way to reach the person, no allowance to charge, and
none of the standing answers the owner wrote. Dvara has all three --
it is the service the person's agents already live behind -- so a
schedule on this road is one HTTP call, ``POST /message``, as that
person, with ``unattended: true``:

* their DAILY ALLOWANCE pays for it, and refuses it when it is spent;
* the owner's RULES apply, deny rules included;
* a question that CAN reach them still does -- on Telegram, with two
  buttons -- and ``allow_tools`` are the ones they answered ahead of
  time, when they accepted the schedule. Dvara grants with them only
  what a question could have granted.

And the answer goes back the same way: ``POST /notify`` puts it on the
person's channels. Samay decides WHETHER to send; Dvara only sends.

CARRIED ON BY ITS THREAD. A run's thread is named after it
(``samay-<schedule>-<run>``), so after a restart the clock can ask Dvara
to go on with the same one (``carry_on: true``); Dvara answers
``nothing`` when it has no stopped turn there, and the run stays
interrupted.

A WORD IS SENT AS A WORD. A schedule whose prompt is a slash word
(``/doctor``: a person's morning check) goes to Dvara as that word
alone. Dvara answers those words itself, with no model, and the run's
framing ("A scheduled run -- ...") is written for a model; around a word
it would only hide it. Its ``NOTHING NEW`` is quiet like any other. And
a word Dvara answered is a run that went well: Dvara's ``ok`` means a
model's turn ended, which a word never is, so only ``refused`` or
``error`` makes it a failure.

A FRESH CONVERSATION EVERY RUN. Each run is its own thread,
``samay-<schedule>-<time>``, so a schedule that has run four hundred
times does not drag four hundred answers into its next prompt; what
the agent should know about the last run, Samay puts in the prompt.

STANDARD LIBRARY ONLY. Samay has no dependencies, and two JSON calls do
not change that.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from samay.runners import JOB, RunResult
from samay.store import Schedule

#: How long a call that is not a turn may take (the agent list, a notice).
QUICK = 30.0
#: How long Dvara waits for a phone in someone's hand before skipping.
PHONE_IN_USE = 600


class DvaraError(RuntimeError):
    """Dvara could not be reached, or said no -- in Dvara's own words."""


@dataclass(frozen=True)
class Dvara:
    url: str
    token: str
    #: Who a schedule made here ("local") runs as and is told as.
    actor: str = ""

    @classmethod
    def from_env(cls) -> Dvara | None:
        """``$SAMAY_DVARA_URL`` and ``$SAMAY_DVARA_TOKEN`` (Dvara's own
        ``$DVARA_TOKEN``), and ``$SAMAY_DVARA_ACTOR``; None when no URL
        is set -- the direct road, with nothing sent anywhere."""
        url = os.environ.get("SAMAY_DVARA_URL", "").strip().rstrip("/")
        if not url:
            return None
        token = os.environ.get("SAMAY_DVARA_TOKEN", "").strip()
        if not token:
            raise DvaraError("SAMAY_DVARA_URL is set but SAMAY_DVARA_TOKEN is "
                             "not: Dvara refuses a caller without its token")
        return cls(url=url, token=token,
                   actor=os.environ.get("SAMAY_DVARA_ACTOR", "").strip())

    def actor_for(self, schedule: Schedule) -> str:
        """The person a schedule is for, as Dvara knows them."""
        if schedule.owner and schedule.owner != "local":
            return schedule.owner
        return self.actor

    # -- calls ---------------------------------------------------------------

    def call(self, method: str, path: str, body: dict | None = None,
             timeout: float = QUICK) -> dict:
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.url + path, data=data, method=method,
            headers={"Authorization": f"Bearer {self.token}",
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as exc:
            try:
                said = json.loads(exc.read() or b"{}").get("detail")
            except (json.JSONDecodeError, AttributeError):
                said = None
            raise DvaraError(f"dvara said {exc.code}: {said or exc.reason}") \
                from None
        except TimeoutError:          # socket.timeout is TimeoutError now
            raise
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise TimeoutError(str(exc.reason)) from None
            raise DvaraError(f"cannot reach dvara at {self.url}: "
                             f"{exc.reason}") from None

    def agents(self) -> list[str]:
        return list(self.call("GET", "/agents").get("agents") or [])

    def notify(self, actor: str, text: str) -> dict:
        return self.call("POST", "/notify", {"actor": actor, "text": text})

    def phone_ready(self, actor: str, wait: float, about: str,
                    phone: str = "") -> str | None:
        """Dvara's check before a run elsewhere works the phone: None to
        go, else why it's skipped. It waits as Dvara does (a phone in hand
        up to PHONE_IN_USE, a locked one ``wait``), so the call does too.
        ``phone``: which of the person's phones, by name."""
        said = self.call("POST", "/phone/ready",
                         {"actor": actor, "wait": wait, "about": about,
                          "phone": phone or True},
                         timeout=PHONE_IN_USE + wait + QUICK)
        return None if said.get("go") else str(said.get("said") or "skipped")


class DvaraRunner:
    """Run a schedule's turn through Dvara, as its person."""

    def __init__(self, dvara: Dvara) -> None:
        self.dvara = dvara

    def can_carry(self, schedule: Schedule, job_id: str) -> bool:
        """Dvara knows whether the thread holds a stopped turn; it is
        asked, and answers ``nothing`` when not."""
        return True

    def run(self, schedule: Schedule, prompt: str) -> RunResult:
        actor = self.dvara.actor_for(schedule)
        if not actor:
            return RunResult(ok=False, stop_reason="error", detail=(
                "this schedule names nobody Dvara knows: add it with --as "
                "ACTOR, or set SAMAY_DVARA_ACTOR"))
        job = JOB.get()
        # A WORD IS SENT AS A WORD: Dvara answers /doctor with no model, so
        # the run's framing (written for a model) would only hide the word
        word = schedule.prompt.strip()
        body = {"actor": actor, "agent": schedule.agent,
                "thread": f"samay-{schedule.id}-{job.id if job else int(time.time())}",
                "text": word if word.startswith("/") else prompt, "unattended": True,
                # so Dvara's page labels the turn as Samay's
                "came_by": "samay",
                "allow_tools": list(schedule.allow_tools),
                "wait": schedule.wait * 60,
                # if the time limit runs out first, Dvara sends the answer
                # itself when it comes -- unless this schedule tells nobody
                "if_late": "keep" if schedule.notify == "never" else "send"}
        if job is not None and job.carry:
            body["carry_on"] = True
        # THE WAITING IS NOT THE WORK. Any run may stop for a yes, and its
        # questions wait `wait` in all (Dvara holds them to that): none of
        # it is the time limit's to spend, or the person's late yes finds
        # a run Samay already gave up on.
        limit = schedule.time_limit + schedule.wait * 60
        if schedule.phone:
            body.update(phone=schedule.phone_name or True,
                        phone_steps=list(schedule.phone_steps))
            # and a phone run may also wait for a phone in someone's hand
            # (up to PHONE_IN_USE) and for its person to unlock it (`wait`)
            limit += PHONE_IN_USE + schedule.wait * 60
        try:
            reply = self.dvara.call("POST", "/message", body, timeout=limit)
        except TimeoutError:
            return RunResult(
                ok=False, timed_out=True, stop_reason="timed_out",
                detail=(f"no answer from dvara within {limit}s (the time limit, "
                        f"{schedule.time_limit}s, and {schedule.wait} min for its "
                        "questions); the turn may still finish there (dvara runs)"
                        + ("" if schedule.notify == "never" else
                           ", and its answer is sent to you when it does")
                        + ". "
                        f"To give it longer: samay limits {schedule.id} "
                        "--time-limit SECONDS, or ask your agent"))
        except DvaraError as exc:
            return RunResult(ok=False, stop_reason="error", detail=str(exc))
        held = reply.get("held")
        if reply.get("stop_reason") == "nothing":
            # asked to carry on, and Dvara had no stopped turn in the thread
            return RunResult(ok=False, stop_reason="nothing",
                             detail=str(reply.get("text") or ""))
        if reply.get("stop_reason") == "skipped":
            # the phone was in use, or stayed locked: nothing was done
            return RunResult(ok=True, stop_reason="skipped", skipped=True,
                             detail=str(reply.get("text") or reply.get("detail") or ""))
        answered = word.startswith("/") and reply.get("stop_reason") not in (
            None, "", "refused", "error")
        return RunResult(
            ok=bool(reply.get("ok")) or answered, text=str(reply.get("text") or ""),
            stop_reason=str(reply.get("stop_reason") or ""),
            detail=str(reply.get("detail") or ""),
            cost_usd=float(reply.get("cost_usd") or 0.0),
            needs=[str(n) for n in reply.get("needs_person") or []],
            busy=[str(b) for b in reply.get("busy") or []],
            refused=[str(r) for r in reply.get("refused") or []],
            dvara_run_id=str(reply.get("run_id") or ""),
            held=bool(held))


class DvaraNotifier:
    """Tell a schedule's person something, on their own channels."""

    def __init__(self, dvara: Dvara) -> None:
        self.dvara = dvara

    def send(self, schedule: Schedule, text: str) -> bool:
        actor = self.dvara.actor_for(schedule)
        if not actor:
            return False
        try:
            sent = self.dvara.notify(actor, text)
        except (DvaraError, TimeoutError):
            return False
        return bool(sent.get("sent") or sent.get("kept"))
