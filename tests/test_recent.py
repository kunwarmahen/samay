"""What went wrong lately, for a harness checking on the house.

The bias: a failure that is never told. ``sarathi doctor`` reads Samay's
``status --json`` and nothing else, so a run that failed at 08:00 has to
be in it, named by its schedule's own words -- and an old failure, or a
run that worked, must not be, or the doctor cries wolf every morning.
"""

from __future__ import annotations

from datetime import timedelta

from samay.status import recent, report
from samay.store import Schedule, Store, now_utc


def schedule(store: Store, prompt: str) -> Schedule:
    return store.add(Schedule(id="", owner="me", prompt=prompt,
                              when={"every": "day", "at": "08:00"}, tz="UTC"))


def test_a_failure_today_is_named_with_its_schedules_words(tmp_path):
    store = Store(tmp_path / "samay.db")
    inbox = schedule(store, "check my   inbox for invoices")
    run = store.start_run(inbox.id, now_utc())
    run.outcome, run.summary = "failed", "the model did not answer"
    store.finish_run(run)
    said = recent(store)
    assert said["runs"] == 1 and said["failed"] == 1
    assert said["named"][0]["prompt"] == "check my inbox for invoices"
    assert said["named"][0]["summary"] == "the model did not answer"


def test_a_run_that_worked_and_an_old_failure_are_not_named(tmp_path):
    store = Store(tmp_path / "samay.db")
    daily = schedule(store, "news")
    old = store.start_run(daily.id, now_utc(), at=now_utc() - timedelta(days=2))
    old.outcome = "failed"
    store.finish_run(old)
    good = store.start_run(daily.id, now_utc())
    good.outcome = "ok"
    store.finish_run(good)
    said = recent(store)
    assert said["runs"] == 1 and said["failed"] == 0 and said["named"] == []


def test_the_status_carries_it(tmp_path):
    store = Store(tmp_path / "samay.db")
    assert report(tmp_path, store)["recent"]["failed"] == 0
