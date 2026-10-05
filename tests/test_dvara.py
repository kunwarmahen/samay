"""The Dvara road: a run as the person, and the answer on their channel.

The bias these tests encode: A SCHEDULE ON THIS ROAD IS EXACTLY ONE
PERSON'S, END TO END. It is checked against Dvara when it is made (the
agent exists, someone to run as is named), it runs as that person with
only what they allowed ahead of time, and its answer goes back to that
same person. And Dvara being down is a failed run that says so, never
a crash of the clock or a hang past the time limit.

Dvara here is a small HTTP server on a real socket, run in a thread,
that answers as the tests tell it and remembers what it was sent.
"""

from __future__ import annotations

import json
import threading
import time
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from samay import schedules
from samay.clock import Clock
from samay.dvara import Dvara, DvaraNotifier, DvaraRunner
from samay.runners import RunResult
from samay.store import Schedule, Store

TOKEN = "a-token-long-enough-to-be-real"


class FakeDvara:
    def __init__(self) -> None:
        self.seen: list[tuple[str, str, dict]] = []
        self.reply: dict = {"ok": True, "text": "2 new mails", "run_id": "r1",
                            "stop_reason": "end_turn", "cost_usd": 0.01,
                            "needs_person": [], "busy": [], "refused": [],
                            "held": None}
        self.status = 200
        self.delay = 0.0
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def _answer(self, body):
                outer.seen.append((self.command, self.path, body))
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    return self._send(401, {"detail": "no"})
                time.sleep(outer.delay)
                if self.path == "/agents":
                    return self._send(200, {"agents": ["reader", "scribe"]})
                if self.path == "/notify":
                    return self._send(200, {"sent": ["telegram"], "kept": []})
                return self._send(outer.status, outer.reply)

            def _send(self, code, body):
                data = json.dumps(body).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                try:
                    self.wfile.write(data)
                except BrokenPipeError:
                    pass

            def do_GET(self):
                self._answer({})

            def do_POST(self):
                size = int(self.headers.get("Content-Length") or 0)
                self._answer(json.loads(self.rfile.read(size) or b"{}"))

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


@pytest.fixture
def dvara():
    fake = FakeDvara()
    yield fake
    fake.close()


def schedule(**kw) -> Schedule:
    base = dict(id="abc123", owner="mahen", prompt="p", when={"every": "1h"},
                tz="UTC", runner="dvara", agent="reader", time_limit=30,
                allow_tools=["browser_*"])
    return Schedule(**{**base, **kw})


class TestTheRun:
    def test_it_runs_as_the_person_unattended_with_what_they_allowed(
            self, dvara):
        runner = DvaraRunner(Dvara(dvara.url, TOKEN))
        result = runner.run(schedule(), "check my mail")
        assert result.ok and result.text == "2 new mails"
        assert result.dvara_run_id == "r1" and result.cost_usd == 0.01
        method, path, body = dvara.seen[-1]
        assert (method, path) == ("POST", "/message")
        assert body["actor"] == "mahen" and body["agent"] == "reader"
        assert body["unattended"] is True
        assert body["allow_tools"] == ["browser_*"]
        assert body["thread"].startswith("samay-abc123-")
        assert body["text"] == "check my mail"

    def test_every_run_is_a_fresh_conversation(self, dvara):
        runner = DvaraRunner(Dvara(dvara.url, TOKEN))
        runner.run(schedule(), "p")
        time.sleep(1.1)
        runner.run(schedule(), "p")
        threads = [b["thread"] for _, _, b in dvara.seen]
        assert threads[0] != threads[1]

    def test_the_three_lists_and_a_hold_come_back(self, dvara):
        dvara.reply.update(ok=False, stop_reason="held",
                           held={"id": "h1", "calls": []},
                           needs_person=["x.com: sign in"],
                           refused=["bash"])
        result = DvaraRunner(Dvara(dvara.url, TOKEN)).run(schedule(), "p")
        assert result.held and result.needs == ["x.com: sign in"]
        assert result.refused == ["bash"]

    def test_dvara_saying_no_is_a_failed_run_in_its_words(self, dvara):
        dvara.status = 400
        dvara.reply = {"detail": "allow_tools goes with unattended: true"}
        result = DvaraRunner(Dvara(dvara.url, TOKEN)).run(schedule(), "p")
        assert not result.ok
        assert result.detail == "dvara said 400: allow_tools goes with unattended: true"

    def test_dvara_down_is_a_failed_run_that_says_where(self):
        result = DvaraRunner(Dvara("http://127.0.0.1:9", TOKEN)).run(
            schedule(), "p")
        assert not result.ok and "cannot reach dvara" in result.detail

    def test_no_answer_within_the_limit_is_timed_out(self, dvara):
        dvara.delay = 3
        started = time.monotonic()
        result = DvaraRunner(Dvara(dvara.url, TOKEN)).run(
            schedule(time_limit=1), "p")
        assert time.monotonic() - started < 3
        assert result.timed_out and "may still finish" in result.detail

    def test_a_local_schedule_runs_as_the_configured_person(self, dvara):
        runner = DvaraRunner(Dvara(dvara.url, TOKEN, actor="owner"))
        runner.run(schedule(owner="local"), "p")
        assert dvara.seen[-1][2]["actor"] == "owner"

    def test_nobody_to_run_as_is_said_before_calling(self, dvara):
        result = DvaraRunner(Dvara(dvara.url, TOKEN)).run(
            schedule(owner="local"), "p")
        assert not result.ok and "--as ACTOR" in result.detail
        assert dvara.seen == []


class TestTheAnswer:
    def test_it_goes_to_the_schedules_person(self, dvara):
        sent = DvaraNotifier(Dvara(dvara.url, TOKEN)).send(schedule(), "news")
        assert sent
        assert dvara.seen[-1][1:] == ("/notify", {"actor": "mahen",
                                                  "text": "news"})

    def test_a_direct_schedule_is_sent_as_the_configured_person(self, dvara):
        notifier = DvaraNotifier(Dvara(dvara.url, TOKEN, actor="owner"))
        assert notifier.send(schedule(owner="local", runner="direct"), "news")
        assert dvara.seen[-1][2]["actor"] == "owner"

    def test_unreachable_is_not_sent_and_not_a_crash(self):
        assert not DvaraNotifier(Dvara("http://127.0.0.1:9", TOKEN)).send(
            schedule(), "news")


class TestMakingOne:
    def make(self, tmp_path, fake, **kw):
        store = Store(tmp_path / "s.sqlite3")
        base = dict(prompt="check", when="every 1h", tz="UTC", runner="dvara",
                    agent="reader", dvara=Dvara(fake.url, TOKEN))
        return schedules.create(store, **{**base, **kw})

    def test_it_runs_as_the_person_named(self, tmp_path, dvara):
        made = self.make(tmp_path, dvara, owner="mahen")
        assert made.owner == "mahen" and made.runner == "dvara"

    def test_an_agent_dvara_does_not_offer_is_refused(self, tmp_path, dvara):
        with pytest.raises(schedules.ScheduleError, match="offers: reader, scribe"):
            self.make(tmp_path, dvara, owner="mahen", agent="nope")

    def test_somebody_must_be_named(self, tmp_path, dvara):
        with pytest.raises(schedules.ScheduleError, match="--as ACTOR"):
            self.make(tmp_path, dvara)

    def test_without_dvara_set_up_it_says_how(self, tmp_path, dvara):
        with pytest.raises(schedules.ScheduleError, match="SAMAY_DVARA_URL"):
            self.make(tmp_path, dvara, owner="mahen", dvara=None)

    def test_dvara_down_when_making_it_is_said(self, tmp_path, dvara):
        with pytest.raises(schedules.ScheduleError, match="cannot reach"):
            self.make(tmp_path, dvara, owner="mahen",
                      dvara=Dvara("http://127.0.0.1:9", TOKEN))


class TestAHeldRun:
    def test_held_is_waiting_not_failing_and_sends_nothing_more(self, tmp_path):
        """The person was already asked, on their channel, by Dvara."""
        start = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)
        now = [start]
        store = Store(tmp_path / "s.sqlite3")

        class Holds:
            def run(self, schedule, prompt):
                return RunResult(ok=False, held=True, stop_reason="held")
        sent = []

        class Inbox:
            def send(self, schedule, text):
                sent.append(text)
                return True
        clock = Clock(store, {"direct": Holds()}, notifier=Inbox(),
                      now=lambda: now[0])
        made = schedules.create(store, prompt="p", when="every 1h", tz="UTC",
                                notify="always", now=start)
        try:
            for _ in range(4):
                now[0] += timedelta(hours=1)
                for future in clock.tick():
                    future.result()
        finally:
            clock.close()
        assert {r.outcome for r in store.runs(made.id)} == {"held"}
        assert store.get(made.id).state == "active"
        assert sent == []


class TestSettings:
    def test_a_url_without_a_token_is_refused(self, monkeypatch):
        from samay.dvara import DvaraError
        monkeypatch.setenv("SAMAY_DVARA_URL", "http://127.0.0.1:8765")
        monkeypatch.delenv("SAMAY_DVARA_TOKEN", raising=False)
        with pytest.raises(DvaraError, match="SAMAY_DVARA_TOKEN"):
            Dvara.from_env()

    def test_no_url_is_the_direct_road(self, monkeypatch):
        monkeypatch.delenv("SAMAY_DVARA_URL", raising=False)
        assert Dvara.from_env() is None
