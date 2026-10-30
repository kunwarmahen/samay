"""The person's side: make one, see it, stop it, take it back.

The bias these tests encode: EVERY SCHEDULE CAN BE SEEN AND UNDONE BY
THE PERSON IT RUNS FOR, and nothing about it is a surprise -- adding one
says back when it will run, a mistake in the ``when`` is refused before
anything is saved, and removing one removes its history with it.
"""

from __future__ import annotations

import json
import sys

import pytest

from samay import schedules
from samay.cli import main
from samay.store import Store


@pytest.fixture
def state(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMAY_STATE", str(tmp_path))
    monkeypatch.setenv("SAMAY_TZ", "America/New_York")
    return tmp_path


def run(capsys, *argv) -> tuple[int, str, str]:
    code = main(list(argv))
    out, err = capsys.readouterr()
    return code, out, err


def add(capsys, *extra, when="every 3h", prompt="check my mail"):
    code, out, _ = run(capsys, "add", prompt, "--when", when, "--json", *extra)
    assert code == 0
    return json.loads(out)


class TestAdding:
    def test_adding_says_when_it_will_run(self, state, capsys):
        code, out, _ = run(capsys, "add", "check my mail", "--when", "at 08:00")
        assert code == 0
        assert "every day at 08:00 -- next:" in out
        assert "(America/New_York)" in out
        assert "samay serve is not running" in out

    def test_a_bad_when_is_refused_and_nothing_saved(self, state, capsys):
        code, _, err = run(capsys, "add", "x", "--when", "every 1m")
        assert code == 2 and "too often" in err
        assert Store(state / "samay.sqlite3").schedules() == []

    def test_an_agent_must_be_a_package(self, state, capsys, tmp_path):
        code, _, err = run(capsys, "add", "x", "--when", "every 1h",
                           "--agent", str(tmp_path))
        assert code == 2 and "no agent.toml" in err

    def test_a_package_is_kept_by_its_full_path(self, state, capsys, tmp_path,
                                                monkeypatch):
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "agent.toml").write_text("")
        monkeypatch.chdir(tmp_path)
        card = add(capsys, "--agent", "pkg")
        assert card["agent"] == str(tmp_path / "pkg")

    def test_there_is_a_cap_per_person(self, state, capsys, monkeypatch):
        monkeypatch.setenv("SAMAY_MAX_SCHEDULES", "2")
        add(capsys)
        add(capsys)
        code, _, err = run(capsys, "add", "x", "--when", "every 1h")
        assert code == 2 and "the most allowed" in err

    def test_the_time_limit_has_bounds(self, state, capsys):
        code, _, err = run(capsys, "add", "x", "--when", "every 1h",
                           "--time-limit", "5")
        assert code == 2 and "between 30 and 3600" in err

    def test_preview_saves_nothing(self, state, capsys):
        code, out, _ = run(capsys, "preview", '{"every": "2h"}', "--json")
        said = json.loads(out)
        assert code == 0 and said["when"] == {"every": "2h"}
        assert len(said["next"]) == 3
        assert Store(state / "samay.sqlite3").schedules() == []


class TestSeeingAndChanging:
    def test_list_shows_the_sentence_and_the_prompt(self, state, capsys):
        card = add(capsys)
        code, out, _ = run(capsys, "list")
        assert code == 0
        assert card["id"] in out and "every 3 hours" in out
        assert "check my mail" in out

    def test_an_id_may_be_shortened_when_it_is_unambiguous(self, state, capsys):
        card = add(capsys)
        code, out, _ = run(capsys, "pause", card["id"][:4])
        assert code == 0 and f"paused {card['id']}" in out

    def test_pause_and_resume(self, state, capsys):
        card = add(capsys)
        run(capsys, "pause", card["id"])
        code, out, _ = run(capsys, "show", card["id"], "--json")
        assert json.loads(out)["state"] == "paused"
        code, out, _ = run(capsys, "resume", card["id"])
        assert code == 0 and "resumed" in out and "next:" in out

    def test_remove_takes_the_history_too(self, state, capsys):
        card = add(capsys)
        store = Store(state / "samay.sqlite3")
        store.start_run(card["id"], schedules.now_utc(), outcome="missed")
        code, out, _ = run(capsys, "rm", card["id"])
        assert code == 0
        assert store.schedules() == [] and store.runs() == []

    def test_an_unknown_id_is_said_plainly(self, state, capsys):
        code, _, err = run(capsys, "show", "nope")
        assert code == 2 and "no schedule 'nope'" in err


class TestRunNow:
    def test_run_now_shows_the_answer(self, state, capsys, tmp_path,
                                      monkeypatch):
        script = tmp_path / "y.py"
        script.write_text(
            "import json\nprint(json.dumps({'format': 'yantra.run.v1', "
            "'ok': True, 'text': 'You have 2 new mails.', "
            "'stop_reason': 'end_turn', 'cost_usd': 0.0, "
            "'needs_person': [], 'busy': []}))\n")
        monkeypatch.setenv("SAMAY_YANTRA", f"{sys.executable} {script}")
        card = add(capsys, "--notify", "always")
        code, out, _ = run(capsys, "run-now", card["id"])
        assert code == 0
        assert "ok" in out and "You have 2 new mails." in out
        code, out, _ = run(capsys, "runs", card["id"], "--json")
        (only,) = json.loads(out)
        assert only["outcome"] == "ok"


class TestMovingZone:
    """A person moved: their schedules made where they were follow them,
    and one they put in another zone on purpose stays. The bias: "every
    morning at 8" firing at 3 am because the person crossed an ocean, or a
    New York market reminder dragged to London with them."""

    def test_their_schedules_in_the_old_zone_follow_them(self, state, capsys):
        weather = add(capsys, "--as", "asha", when="at 08:00", prompt="the weather")
        market = add(capsys, "--as", "asha", "--tz", "Asia/Kolkata", when="at 09:30",
                     prompt="market open")
        others = add(capsys, "--as", "ravi", when="at 08:00", prompt="ravi's")
        code, out, _ = run(capsys, "zone", "asha", "--from", "America/New_York",
                           "--to", "Europe/London", "--json")
        assert code == 0
        assert [c["id"] for c in json.loads(out)["moved"]] == [weather["id"]]
        store = Store(state / "samay.sqlite3")
        moved = store.get(weather["id"])
        assert moved.tz == "Europe/London"
        at = schedules.from_iso(moved.next_at).astimezone(schedules.ZoneInfo("Europe/London"))
        assert (at.hour, at.minute) == (8, 0)                    # 8 where she is now
        assert store.get(market["id"]).tz == "Asia/Kolkata"      # put there on purpose
        assert store.get(others["id"]).tz == "America/New_York"  # not hers

    def test_blank_is_this_machines_zone_and_a_bad_name_is_refused(self, state, capsys):
        card = add(capsys, "--as", "asha", when="at 08:00")
        code, out, _ = run(capsys, "zone", "asha", "--from", "", "--to", "Asia/Tokyo")
        assert code == 0 and "moved 1 schedule of asha" in out and "(Asia/Tokyo)" in out
        code, _, err = run(capsys, "zone", "asha", "--from", "Asia/Tokyo", "--to", "Mars/Base")
        assert code == 2 and "not a time zone's name" in err
        assert Store(state / "samay.sqlite3").get(card["id"]).tz == "Asia/Tokyo"
        code, out, _ = run(capsys, "zone", "asha", "--from", "Asia/Tokyo", "--to", "Asia/Tokyo")
        assert "moved 0 schedules" in out


class TestLimits:
    def test_a_schedule_gets_more_time_from_its_next_run(self, state, capsys):
        sid = add(capsys)["id"]
        code, out, _ = run(capsys, "limits", sid, "--time-limit", "1800")
        assert code == 0
        assert out.strip() == f"{sid} runs get 30 min of work, and 30 min for their questions"
        assert Store(state / "samay.sqlite3").get(sid).time_limit == 1800

    def test_nothing_to_change_or_out_of_range_is_refused(self, state, capsys):
        sid = add(capsys)["id"]
        code, _, err = run(capsys, "limits", sid)
        assert code == 2 and "say what to change" in err
        code, _, err = run(capsys, "limits", sid, "--time-limit", "9000")
        assert code == 2 and "between 30 and 3600" in err
