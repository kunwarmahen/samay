"""The direct road: Yantra as a program, and only its JSON believed.

The bias these tests encode: A RUN THAT GOES WRONG MUST COME BACK AS A
RESULT, NEVER AS SILENCE OR A HANG. A program that hangs is killed with
everything it started; one that prints nothing, or a shape this Samay
does not know, is a failed run that says why. And what the person
accepted -- the tools named ahead of time, a profile of the schedule's
own -- is what reaches Yantra, nothing more.

``yantra`` here is a small Python script the tests write, which records
how it was started and answers as told.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from samay.runners import DirectRunner, RunnerMissing, find_yantra
from samay.store import Schedule


def fake_yantra(tmp_path: Path, body: str) -> list[str]:
    script = tmp_path / "fake_yantra.py"
    script.write_text(
        "import json, os, sys, time\n"
        f"open({str(tmp_path / 'seen.json')!r}, 'w').write(json.dumps("
        "{'argv': sys.argv[1:], 'cwd': os.getcwd(), "
        "'unattended': os.environ.get('YANTRA_UNATTENDED'), "
        "'profile': os.environ.get('YANTRA_BROWSER_PROFILE')}))\n" + body)
    return [sys.executable, str(script)]


def answer(**fields) -> str:
    data = {"format": "yantra.run.v1", "ok": True, "text": "hi",
            "stop_reason": "end_turn", "detail": "", "cost_usd": 0.0012,
            "priced": True, "needs_person": [], "busy": [], "refused": [],
            **fields}
    return f"print('banner line'); print({json.dumps(json.dumps(data))})\n"


def schedule(**kw) -> Schedule:
    base = dict(id="abc123", owner="local", prompt="p", when={"every": "1h"},
                tz="UTC", time_limit=30)
    return Schedule(**{**base, **kw})


def seen(tmp_path) -> dict:
    return json.loads((tmp_path / "seen.json").read_text())


class TestWhatIsPassed:
    def test_unattended_json_and_the_allowed_tools(self, tmp_path):
        runner = DirectRunner(tmp_path / "work",
                              command=fake_yantra(tmp_path, answer()))
        result = runner.run(schedule(allow_tools=["browser_*", "web_fetch"],
                                     agent="/pkg"), "do it")
        assert result.ok and result.text == "hi"
        got = seen(tmp_path)
        assert got["argv"] == ["--cwd", str(tmp_path / "work" / "abc123"),
                               "--json", "--unattended", "--agent", "/pkg",
                               "--allow-tools", "browser_*",
                               "--allow-tools", "web_fetch", "--prompt", "do it"]
        assert got["unattended"] == "1"
        assert (tmp_path / "work" / "abc123").is_dir()

    def test_a_profile_of_its_own_reaches_the_browser(self, tmp_path):
        runner = DirectRunner(tmp_path, command=fake_yantra(tmp_path, answer()))
        runner.run(schedule(browser_profile="/profiles/sched"), "p")
        assert seen(tmp_path)["profile"] == "/profiles/sched"

    def test_it_starts_where_yantra_keeps_its_env(self, tmp_path):
        home = tmp_path / "yantra-home"
        home.mkdir()
        runner = DirectRunner(tmp_path / "work", home=home,
                              command=fake_yantra(tmp_path, answer()))
        runner.run(schedule(), "p")
        assert seen(tmp_path)["cwd"] == str(home)


class TestWhatComesBack:
    def test_cost_needs_and_busy_are_read(self, tmp_path):
        body = answer(ok=True, needs_person=["x.com: sign in"],
                      busy=["profile in use"], refused=["bash"], cost_usd=0.5)
        result = DirectRunner(tmp_path, command=fake_yantra(tmp_path, body)
                              ).run(schedule(), "p")
        assert result.needs == ["x.com: sign in"]
        assert result.refused == ["bash"]
        assert result.busy == ["profile in use"]
        assert result.cost_usd == 0.5

    def test_a_failed_turn_still_answers(self, tmp_path):
        body = answer(ok=False, stop_reason="error", detail="nobody to ask") \
            + "sys.exit(1)\n"
        result = DirectRunner(tmp_path, command=fake_yantra(tmp_path, body)
                              ).run(schedule(), "p")
        assert not result.ok and result.detail == "nobody to ask"

    def test_no_answer_keeps_the_end_of_what_it_said(self, tmp_path):
        body = "sys.stderr.write('error: no API key\\n'); sys.exit(2)\n"
        result = DirectRunner(tmp_path, command=fake_yantra(tmp_path, body)
                              ).run(schedule(), "p")
        assert not result.ok and result.detail == "error: no API key"

    def test_an_unknown_format_is_refused_not_guessed(self, tmp_path):
        body = answer(format="yantra.run.v9")
        result = DirectRunner(tmp_path, command=fake_yantra(tmp_path, body)
                              ).run(schedule(), "p")
        assert not result.ok and "yantra.run.v9" in result.detail

    def test_a_program_that_cannot_start_is_a_result(self, tmp_path):
        result = DirectRunner(tmp_path, command=[str(tmp_path / "nope")]
                              ).run(schedule(), "p")
        assert not result.ok and "could not start" in result.detail


class TestTheTimeLimit:
    def test_a_hang_is_killed_with_what_it_started(self, tmp_path):
        """The child it spawns -- a browser, in life -- goes too."""
        marker = tmp_path / "child.pid"
        body = ("import subprocess\n"
                "child = subprocess.Popen([sys.executable, '-c', "
                "'import time; time.sleep(60)'])\n"
                f"open({str(marker)!r}, 'w').write(str(child.pid))\n"
                "time.sleep(60)\n")
        runner = DirectRunner(tmp_path, command=fake_yantra(tmp_path, body))
        started = time.monotonic()
        result = runner.run(schedule(time_limit=1), "p")
        assert time.monotonic() - started < 10
        assert result.timed_out and not result.ok
        assert "time limit" in result.detail
        child = int(marker.read_text())
        for _ in range(50):
            try:
                os.kill(child, 0)
            except ProcessLookupError:
                break
            time.sleep(0.1)
        else:
            pytest.fail("the child outlived the time limit")


class TestFindingYantra:
    def test_the_setting_may_be_several_words(self, monkeypatch):
        monkeypatch.setenv("SAMAY_YANTRA", "uv run --project '/my dir' yantra")
        assert find_yantra() == ["uv", "run", "--project", "/my dir", "yantra"]

    def test_not_found_says_how_to_set_it(self, monkeypatch, tmp_path):
        monkeypatch.delenv("SAMAY_YANTRA", raising=False)
        monkeypatch.setenv("PATH", str(tmp_path))
        monkeypatch.setattr(sys, "executable", str(tmp_path / "python"))
        with pytest.raises(RunnerMissing, match="SAMAY_YANTRA"):
            find_yantra()
