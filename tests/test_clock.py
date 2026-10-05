"""The clock's rules, each against the way an unwatched schedule goes wrong.

The bias these tests encode: A SCHEDULE NOBODY IS WATCHING MUST NEITHER
SPEND TWICE NOR FAIL QUIETLY. So a missed time runs at most once and a
backlog never; a crash does not rerun the time it was on; a run that
needs a person stops the schedule and says so; three failures in a row
stop it and say so; and a busy browser is neither a failure nor news.

Time is a fake the test moves by hand, and the runner is a fake that
answers what each test tells it to -- no process, no model, no sleep.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from samay import schedules
from samay.clock import Clock, compose, is_quiet
from samay.runners import RunResult
from samay.store import Store, iso

START = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)       # a Monday


class FakeTime:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        return self.at

    def move(self, **kw) -> None:
        self.at += timedelta(**kw)


class FakeRunner:
    def __init__(self, *results: RunResult) -> None:
        self.results = list(results)
        self.prompts: list[str] = []

    def run(self, schedule, prompt):
        self.prompts.append(prompt)
        return self.results.pop(0) if self.results else RunResult(ok=True, text="done")


class Inbox:
    def __init__(self) -> None:
        self.sent: list[str] = []

    def send(self, schedule, text):
        self.sent.append(text)
        return True


@pytest.fixture
def world(tmp_path):
    clock_time = FakeTime(START)
    store = Store(tmp_path / "s.sqlite3")
    runner = FakeRunner()
    inbox = Inbox()
    clock = Clock(store, {"direct": runner}, notifier=inbox, now=clock_time)
    yield clock_time, store, runner, inbox, clock
    clock.close()


def add(store, when="every 1h", notify="when_new", **kw):
    return schedules.create(store, prompt="check my mail", when=when, tz="UTC",
                            notify=notify, now=START, **kw)


def tick(clock):
    for future in clock.tick():
        future.result()


class TestOnTime:
    def test_nothing_runs_before_its_time(self, world):
        time, store, runner, _, clock = world
        add(store)
        time.move(minutes=59)
        tick(clock)
        assert runner.prompts == []

    def test_a_due_time_runs_and_the_next_one_is_set(self, world):
        time, store, runner, inbox, clock = world
        s = add(store)
        time.move(hours=1)
        tick(clock)
        assert len(runner.prompts) == 1
        assert store.get(s.id).next_at == iso(START + timedelta(hours=2))
        (run,) = store.runs(s.id)
        assert run.outcome == "ok" and inbox.sent == ["done"]

    def test_a_once_schedule_is_done_after_it_runs(self, world):
        time, store, runner, _, clock = world
        s = add(store, when="once 2026-10-05T13:00")
        time.move(hours=1)
        tick(clock)
        assert store.get(s.id).state == "done"
        time.move(hours=5)
        tick(clock)
        assert len(runner.prompts) == 1


class TestMissedTimes:
    def test_a_little_late_still_runs(self, world):
        time, store, runner, _, clock = world
        add(store)
        time.move(hours=1, minutes=20)                 # grace is 30 min
        tick(clock)
        assert len(runner.prompts) == 1

    def test_too_late_is_written_down_and_not_run(self, world):
        time, store, runner, _, clock = world
        s = add(store)
        time.move(hours=1, minutes=45)
        tick(clock)
        assert runner.prompts == []
        (run,) = store.runs(s.id)
        assert run.outcome == "missed" and "not running" in run.detail

    def test_a_long_outage_is_one_row_not_a_backlog(self, world):
        """Twelve hourly checks fired at once are twelve bills for one
        answer."""
        time, store, runner, _, clock = world
        s = add(store)
        time.move(hours=12, minutes=40)
        tick(clock)
        tick(clock)
        assert runner.prompts == []
        assert [r.outcome for r in store.runs(s.id)] == ["missed"]
        assert store.get(s.id).next_at == iso(START + timedelta(hours=13))


class TestOneAtATime:
    def test_a_time_that_comes_while_the_last_run_goes_is_skipped(self, world):
        time, store, runner, _, clock = world
        s = add(store)
        clock._running.add(s.id)                         # the 13:00 run, still going
        time.move(hours=1)
        tick(clock)
        assert runner.prompts == []
        assert store.runs(s.id)[0].outcome == "skipped"

    def test_a_run_in_another_process_counts(self, world):
        time, store, runner, _, clock = world
        s = add(store)
        time.move(minutes=55)
        store.start_run(s.id, time(), at=time())         # 'running', from the CLI
        time.move(minutes=5)
        tick(clock)
        assert runner.prompts == []

    def test_a_running_row_older_than_its_time_limit_is_stale(self, world):
        """A row a dead process left behind does not block the schedule
        for ever, even before the next start marks it interrupted."""
        time, store, runner, _, clock = world
        s = add(store)
        store.start_run(s.id, START, at=START)
        time.move(hours=1)
        tick(clock)
        assert len(runner.prompts) == 1

    def test_a_crash_does_not_run_the_same_time_again(self, world):
        time, store, runner, _, clock = world
        s = add(store)
        time.move(hours=1)
        store.update(s.id, next_at=iso(START + timedelta(hours=2)))  # claimed
        store.start_run(s.id, START + timedelta(hours=1), at=time())  # then died
        assert store.interrupt_unfinished() == 1
        tick(clock)
        assert runner.prompts == []
        assert store.runs(s.id)[0].outcome == "interrupted"


class TestFailures:
    def test_three_in_a_row_pause_it_and_say_so_once(self, world):
        time, store, runner, inbox, clock = world
        runner.results = [RunResult(ok=False, detail="model unreachable")] * 3
        s = add(store)
        for _ in range(3):
            time.move(hours=1)
            tick(clock)
        schedule = store.get(s.id)
        assert schedule.state == "paused"
        assert "failed 3 times in a row" in schedule.paused_because
        assert len(inbox.sent) == 1 and "samay resume" in inbox.sent[0]
        time.move(hours=1)
        tick(clock)
        assert len(runner.prompts) == 3

    def test_a_good_run_resets_the_count(self, world):
        time, store, runner, _, clock = world
        runner.results = [RunResult(ok=False), RunResult(ok=False),
                          RunResult(ok=True, text="fine"), RunResult(ok=False)]
        s = add(store)
        for _ in range(4):
            time.move(hours=1)
            tick(clock)
        assert store.get(s.id).state == "active"
        assert store.get(s.id).failures == 1

    def test_needing_a_person_pauses_at_once_with_what_is_needed(self, world):
        time, store, runner, inbox, clock = world
        runner.results = [RunResult(ok=True, text="x.com wants a sign-in",
                                    needs=["https://x.com/login: sign in again"])]
        s = add(store, notify="always")
        time.move(hours=1)
        tick(clock)
        schedule = store.get(s.id)
        assert schedule.state == "paused"
        assert schedule.paused_because == \
            "needs you: https://x.com/login: sign in again"
        assert store.runs(s.id)[0].outcome == "needs_person"
        assert any("sign in again" in m for m in inbox.sent)

    def test_a_busy_browser_is_not_a_failure_and_not_news(self, world):
        time, store, runner, inbox, clock = world
        runner.results = [RunResult(ok=True, text="the browser was busy",
                                    busy=["profile in use"])] * 4
        s = add(store, notify="always")
        for _ in range(4):
            time.move(hours=1)
            tick(clock)
        assert store.get(s.id).state == "active"
        assert {r.outcome for r in store.runs(s.id)} == {"busy"}
        assert inbox.sent == []

    def test_a_runner_that_raises_is_a_failed_run(self, world):
        time, store, _, _, clock = world

        class Broken:
            def run(self, schedule, prompt):
                raise RuntimeError("boom")
        clock.runners["direct"] = Broken()
        s = add(store)
        time.move(hours=1)
        tick(clock)
        run = store.runs(s.id)[0]
        assert run.outcome == "failed" and "boom" in run.detail
        assert s.id not in clock._running


class TestWhatIsSent:
    def test_nothing_new_is_kept_and_not_sent(self, world):
        time, store, runner, inbox, clock = world
        runner.results = [RunResult(ok=True, text="**NOTHING NEW.**")]
        s = add(store, notify="when_new")
        time.move(hours=1)
        tick(clock)
        assert store.runs(s.id)[0].outcome == "quiet"
        assert inbox.sent == []

    def test_never_keeps_everything_and_sends_nothing(self, world):
        time, store, runner, inbox, clock = world
        s = add(store, notify="never")
        time.move(hours=1)
        tick(clock)
        assert store.runs(s.id)[0].outcome == "ok" and inbox.sent == []

    def test_always_sends_even_words_that_look_quiet(self, world):
        time, store, runner, inbox, clock = world
        runner.results = [RunResult(ok=True, text="NOTHING NEW")]
        add(store, notify="always")
        time.move(hours=1)
        tick(clock)
        assert inbox.sent == ["NOTHING NEW"]

    @pytest.mark.parametrize("text,quiet", [
        ("NOTHING NEW", True), ("Nothing new.", True), ("`NOTHING NEW`", True),
        ("Nothing new from the bank, but one from your landlord", False),
        ("", False)])
    def test_what_counts_as_quiet(self, text, quiet):
        assert is_quiet(text) is quiet


class TestThePrompt:
    def test_the_agent_is_told_it_is_unwatched_and_when_to_stay_quiet(
            self, world):
        _, store, _, _, _ = world
        s = add(store)
        prompt = compose(s, None)
        assert prompt.startswith("(A scheduled run -- every hour.")
        assert "check my mail" in prompt
        assert "reply with exactly: NOTHING NEW" in prompt
        assert "never reply NOTHING NEW; say what stopped you" in prompt

    def test_the_last_run_is_carried_in(self, world):
        time, store, runner, _, clock = world
        runner.results = [RunResult(ok=True, text="2 new mails from the bank")]
        add(store)
        time.move(hours=1)
        tick(clock)
        time.move(hours=1)
        tick(clock)
        assert "(Last run, Mon 5 Oct 13:00: 2 new mails from the bank)" in \
            runner.prompts[1]


class TestRunNow:
    def test_an_extra_run_leaves_the_next_time_alone(self, world):
        _, store, runner, _, clock = world
        s = add(store)
        run = clock.run_now(s.id)
        assert run.outcome == "ok" and len(runner.prompts) == 1
        assert store.get(s.id).next_at == iso(START + timedelta(hours=1))

    def test_not_while_it_is_running(self, world):
        _, store, _, _, clock = world
        s = add(store)
        clock._running.add(s.id)
        with pytest.raises(RuntimeError, match="running already"):
            clock.run_now(s.id)


class TestPausedWhileRunning:
    def test_a_pause_during_a_run_is_kept(self, world):
        time, store, _, _, clock = world
        s = add(store)

        class PausesMidRun:
            def run(self, schedule, prompt):
                schedules.pause(store, schedule.id)
                return RunResult(ok=False)
        clock.runners["direct"] = PausesMidRun()
        time.move(hours=1)
        tick(clock)
        assert store.get(s.id).paused_because == "paused by you"


class TestRefusedTools:
    def test_a_refused_tool_is_kept_but_does_not_stop_the_schedule(self, world):
        """The model was told no and answered anyway: a person may want
        to allow it next time, but nothing needs them now."""
        time, store, runner, inbox, clock = world
        runner.results = [RunResult(ok=True, text="here you go",
                                    refused=["bash"])]
        s = add(store, notify="always")
        time.move(hours=1)
        tick(clock)
        run = store.runs(s.id)[0]
        assert run.outcome == "ok" and run.refused == ["bash"]
        assert store.get(s.id).state == "active"
        assert inbox.sent == ["here you go"]


class TestSummary:
    def test_an_introducing_line_takes_the_next_one_with_it(self):
        from samay.clock import summarize
        text = "Here are the top 3 stories:\n\n1. First story\n2. Second"
        assert summarize(text) == "Here are the top 3 stories: 1. First story"

    def test_markdown_is_not_part_of_the_summary(self):
        from samay.clock import summarize
        assert summarize("## **Two new mails**\nmore") == "Two new mails"
