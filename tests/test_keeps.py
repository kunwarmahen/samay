"""`samay keeps`: where the schedules and the logbook are, for a backup.

The bias: A BACKUP THAT MISSES THE LOGBOOK, OR MAKES ONE. Sarathi packs
what this says and nothing else, so the folder must be the one the clock
uses ($SAMAY_STATE, --state), and asking must never create a database
in a folder that had none -- a fresh computer asked before a restore
would otherwise hold an empty logbook where the real one goes.
"""

from __future__ import annotations

import json

from samay.cli import main


def test_the_place_is_samay_state_and_asking_makes_nothing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("SAMAY_STATE", str(tmp_path / "samay"))
    assert main(["keeps", "--json"]) == 0
    said = json.loads(capsys.readouterr().out)
    assert said["format"] == "samay.keeps.v1"
    place = said["keeps"][0]
    assert place["path"] == str(tmp_path / "samay") and place["exists"] is False
    assert not (tmp_path / "samay").exists()


def test_the_running_clocks_record_is_left_out_and_the_logbook_is_not(tmp_path, capsys):
    assert main(["--state", str(tmp_path), "keeps", "--json"]) == 0
    place = json.loads(capsys.readouterr().out)["keeps"][0]
    assert place["path"] == str(tmp_path) and place["exists"] is True
    assert "serve.json" in place["leave_out"]
    assert "samay.sqlite3" not in place["leave_out"] and "work" not in place["leave_out"]
