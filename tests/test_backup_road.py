"""The backup road: Sarathi asked to back the house up, every night.

The bias: A BACKUP THAT STOPPED AND NOBODY HEARD. A night that went well
is NOTHING NEW (nobody wants a message every morning saying it worked);
everything else is a failed run that says why -- Sarathi unreachable, no
passphrase chosen yet (its own words, which say what to type), a backup
made without part of the house, or an answer this Samay can't read.
"""

from __future__ import annotations

import io
import urllib.error

import pytest
from test_runners import schedule

from samay import schedules
from samay.clock import is_quiet
from samay.runners import BackupRunner
from samay.schedules import ScheduleError
from samay.store import Store

MADE = {"format": "sarathi.backup.made.v1", "ok": True, "bytes": 3 * 1024 ** 2,
        "file": "/b/sarathi-beast-20261024-023000.sarathi-backup", "problems": [],
        "removed": ["sarathi-beast-20261017-023000.sarathi-backup"]}


def run(data=None, post=None):
    runner = BackupRunner(url="http://home/api/backup", token="t",
                          post=post or (lambda url, token, timeout: data))
    return runner.run(schedule(runner="backup"), "the house, backed up")


def test_a_night_that_went_well_is_quiet_and_says_where():
    result = run(MADE)
    assert result.ok and is_quiet(result.text)
    assert "sarathi-beast-20261024-023000" in result.text and "3.0 MB" in result.text
    assert "1 older removed" in result.text


def test_a_backup_missing_part_of_the_house_fails_and_says_what():
    result = run({**MADE, "ok": False, "problems": ["setu doesn't say what it keeps"]})
    assert not result.ok and not is_quiet(result.text)
    assert "not in it: setu doesn't say what it keeps" in result.text
    assert "setu" in result.detail


def test_no_passphrase_yet_fails_in_sarathis_own_words():
    def refused(url, token, timeout):
        raise urllib.error.HTTPError(url, 409, "Conflict", {}, io.BytesIO(
            b'{"detail": "there is no backup passphrase yet: run `sarathi backup` once"}'))
    result = run(post=refused)
    assert not result.ok and "run `sarathi backup` once" in result.detail


def test_nobody_to_ask_or_an_unknown_answer_fails_out_loud():
    assert "sarathi up" in BackupRunner(url="", token="").run(
        schedule(runner="backup"), "x").detail
    assert not run({"format": "sarathi.backup.made.v9"}).ok


def test_the_key_goes_in_a_header_and_it_waits_as_long_as_the_schedule_allows():
    seen = {}

    def post(url, token, timeout):
        seen.update(url=url, token=token, timeout=timeout)
        return MADE
    BackupRunner(url="http://home/api/backup", token="k", post=post).run(
        schedule(runner="backup", time_limit=3600), "x")
    assert seen == {"url": "http://home/api/backup", "token": "k", "timeout": 3600}


def test_a_backup_schedule_takes_no_agent(tmp_path):
    store = Store(tmp_path / "samay.db")
    made = schedules.create(store, prompt="the house, backed up", when="at 02:30",
                            runner="backup")
    assert made.runner == "backup"
    with pytest.raises(ScheduleError, match="no agent"):
        schedules.create(store, prompt="x", when="at 02:30", runner="backup",
                         agent="minder")
