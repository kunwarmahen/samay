"""A run a restart stopped, carried on from its last step (runners.py ``Job``).

The bias these tests encode: A RESTART THAT EITHER LOSES A RUN OR DOES IT
TWICE. Before, a run going when Samay stopped was only ever marked
``interrupted`` -- the steps it had done were lost, and the person found
out the job was half done by looking. Carrying on must not become the
opposite failure, the time run again from the top: so it goes on only
from what was SAVED, only soon after (within the schedule's grace), and
never beside a Yantra still at it. Anything else is ``interrupted``, as
before.
"""

from __future__ import annotations

import fcntl
import json
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from samay import schedules
from samay.clock import Clock
from samay.dvara import Dvara, DvaraRunner
from samay.runners import JOB, DirectRunner, Job, RunResult, stopped_part_way
from samay.store import Store

from tests.test_dvara import TOKEN, FakeDvara, schedule

START = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def job_file(path: Path, *, unfinished: bool) -> Path:
    """A checkpoint file the way ``yantra --job`` writes one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE checkpoints (id INTEGER PRIMARY KEY, session_id "
                   "TEXT, version INTEGER, created_at TEXT, payload TEXT)")
        payload = {"history": []}
        if unfinished:
            payload["unfinished"] = {"message": "check my mail", "steps": 2}
        db.execute("INSERT INTO checkpoints (session_id, version, created_at, payload) "
                   "VALUES ('job', 1, '', ?)", (json.dumps(payload),))
    return path


class Carrier:
    """A runner that can carry on, and says what it was asked to do."""

    def __init__(self, can=True, result=None):
        self.can = can
        self.result = result or RunResult(ok=True, text="2 new mails")
        self.jobs: list[Job | None] = []

    def can_carry(self, schedule, job_id):
        return self.can

    def run(self, schedule, prompt):
        self.jobs.append(JOB.get())
        return self.result


def stopped_run(store, *, minutes_ago: int):
    """A schedule, and a run of it a dead Samay left ``running``."""
    made = schedules.create(store, prompt="check my mail", when="every 1h", tz="UTC",
                            notify="always", now=START - timedelta(hours=2))
    run = store.start_run(made.id, START - timedelta(minutes=minutes_ago),
                          at=START - timedelta(minutes=minutes_ago))
    return made, run


def restart(store, runner):
    clock = Clock(store, {"direct": runner}, now=lambda: START)
    try:
        interrupted = clock.carry_on_or_interrupt()
        clock._pool.shutdown(wait=True)
    finally:
        clock.close()
    return interrupted


class TestTheClock:
    def test_a_recent_run_is_carried_on_in_its_own_row(self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        made, run = stopped_run(store, minutes_ago=5)
        runner = Carrier()

        assert restart(store, runner) == 0

        assert runner.jobs == [Job(run.id, carry=True)]
        (only,) = store.runs(made.id)
        assert only.id == run.id and only.outcome == "ok"
        assert only.detail.startswith("carried on after a restart")

    def test_one_from_too_long_ago_is_interrupted_not_run(self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        made, _ = stopped_run(store, minutes_ago=45)     # grace is 30 min
        runner = Carrier()

        assert restart(store, runner) == 1

        assert runner.jobs == []
        (only,) = store.runs(made.id)
        assert only.outcome == "interrupted" and "too long ago" in only.detail

    def test_with_nothing_saved_it_is_interrupted_not_started_over(self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        made, _ = stopped_run(store, minutes_ago=5)

        assert restart(store, Carrier(can=False)) == 1
        assert store.runs(made.id)[0].outcome == "interrupted"

    def test_a_road_that_says_nothing_was_there_leaves_it_interrupted(self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        made, _ = stopped_run(store, minutes_ago=5)
        runner = Carrier(result=RunResult(ok=False, stop_reason="nothing"))

        restart(store, runner)

        (only,) = store.runs(made.id)
        assert only.outcome == "interrupted" and "nothing was saved" in only.detail

    def test_a_road_that_cannot_carry_on_is_interrupted(self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        made, _ = stopped_run(store, minutes_ago=5)

        class Plain:
            def run(self, schedule, prompt):
                raise AssertionError("must not run")

        assert restart(store, Plain()) == 1
        assert "cannot carry a run on" in store.runs(made.id)[0].detail

    def test_every_run_carries_its_own_job(self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        made = schedules.create(store, prompt="p", when="every 1h", tz="UTC",
                                notify="always", now=START)
        runner = Carrier()
        clock = Clock(store, {"direct": runner}, now=lambda: START + timedelta(hours=1))
        try:
            for future in clock.tick():
                future.result()
        finally:
            clock.close()
        (run,) = store.runs(made.id)
        assert runner.jobs == [Job(run.id, carry=False)]


class TestTheDirectRoad:
    def test_its_yantra_is_given_the_job_file(self, tmp_path):
        runner = DirectRunner(tmp_path, command=["yantra"])
        token = JOB.set(Job("r1"))
        try:
            argv = runner.argv(schedule(runner="direct"), "p")
        finally:
            JOB.reset(token)
        at = argv.index("--job")
        assert argv[at + 1] == str(tmp_path / ".jobs" / "abc123-r1.sqlite")

    def test_only_a_stopped_checkpoint_can_be_carried_on(self, tmp_path):
        assert stopped_part_way(job_file(tmp_path / "a.sqlite", unfinished=True))
        assert not stopped_part_way(job_file(tmp_path / "b.sqlite", unfinished=False))
        assert not stopped_part_way(tmp_path / "missing.sqlite")

    def test_a_job_a_yantra_still_holds_is_left_alone(self, tmp_path):
        path = job_file(tmp_path / "a.sqlite", unfinished=True)
        with open(f"{path}.lock", "a") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            assert not stopped_part_way(path)
        assert stopped_part_way(path)

    def test_a_finished_run_keeps_its_file_for_its_steps_and_drops_its_lock(self, tmp_path):
        script = tmp_path / "fake-yantra"
        script.write_text("#!/bin/sh\necho '{\"format\": \"yantra.run.v1\", "
                          "\"ok\": true, \"text\": \"hi\", \"stop_reason\": "
                          "\"end_turn\"}'\n")
        script.chmod(0o755)
        runner = DirectRunner(tmp_path / "work", command=[str(script)])
        kept = job_file(runner.job_file(schedule(runner="direct"), Job("r1")),
                        unfinished=False)
        Path(f"{kept}.lock").write_text("")
        token = JOB.set(Job("r1"))
        try:
            assert runner.run(schedule(runner="direct", phone=False), "p").ok
        finally:
            JOB.reset(token)
        assert kept.exists() and not Path(f"{kept}.lock").exists()

    def test_job_files_are_let_go_after_thirty_days(self, tmp_path):
        import os
        import time
        runner = DirectRunner(tmp_path / "work", command=["yantra"])
        old = job_file(tmp_path / "work" / ".jobs" / "abc-old.sqlite", unfinished=False)
        new = job_file(tmp_path / "work" / ".jobs" / "abc-new.sqlite", unfinished=False)
        month_ago = time.time() - 31 * 86400
        os.utime(old, (month_ago, month_ago))

        assert runner.prune_jobs() == 1
        assert not old.exists() and new.exists()


class TestSteps:
    def test_a_direct_runs_steps_are_read_by_yantra_from_its_file(self, tmp_path):
        script = tmp_path / "fake-yantra"
        script.write_text('#!/bin/sh\n[ "$1" = "--steps" ] && echo \'{"format": '
                          '"yantra.steps.v1", "steps": [{"n": 1, "tool": "read_file"}]}\'\n')
        script.chmod(0o755)
        runner = DirectRunner(tmp_path / "work", command=[str(script)])
        job_file(runner.job_file(schedule(runner="direct"), Job("r1")), unfinished=False)

        view = runner.steps(schedule(runner="direct"), "r1")

        assert view["steps"][0]["tool"] == "read_file"
        with pytest.raises(LookupError, match="not kept"):
            runner.steps(schedule(runner="direct"), "gone")

    def test_the_page_asks_dvara_for_a_run_it_ran(self, tmp_path, dvara):
        from samay.http import Api
        store = Store(tmp_path / "s.sqlite3")
        made = schedules.create(store, prompt="p", when="every 1h", tz="UTC",
                                notify="always", now=START)
        run = store.start_run(made.id, START, at=START)
        run.dvara_run_id, run.outcome = "d-77", "ok"
        store.finish_run(run, at=START)
        dvara.reply = {"format": "yantra.steps.v1", "steps": [], "run": "d-77"}
        clock = Clock(store, {}, now=lambda: START)
        try:
            api = Api(store, clock, tmp_path, dvara=Dvara(dvara.url, TOKEN))
            assert api.run_steps(run.id)["run"] == "d-77"
        finally:
            clock.close()
        assert dvara.seen[-1][:2] == ("GET", "/runs/d-77/steps")


@pytest.fixture
def dvara():
    fake = FakeDvara()
    yield fake
    fake.close()


class TestTheDvaraRoad:
    def test_the_thread_is_the_runs_and_a_carry_on_says_so(self, dvara):
        runner = DvaraRunner(Dvara(dvara.url, TOKEN))
        token = JOB.set(Job("r9", carry=True))
        try:
            runner.run(schedule(), "check my mail")
        finally:
            JOB.reset(token)
        body = dvara.seen[-1][2]
        assert body["thread"] == "samay-abc123-r9" and body["carry_on"] is True

    def test_nothing_to_carry_on_comes_back_as_nothing(self, dvara):
        dvara.reply = {"ok": False, "text": "Nothing stopped part way here.",
                       "stop_reason": "nothing"}
        runner = DvaraRunner(Dvara(dvara.url, TOKEN))
        token = JOB.set(Job("r9", carry=True))
        try:
            result = runner.run(schedule(), "p")
        finally:
            JOB.reset(token)
        assert result.stop_reason == "nothing" and not result.ok
