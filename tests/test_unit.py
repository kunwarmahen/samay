"""`samay unit`: the clock kept running by the machine's service manager.

The bias these tests encode: A SERVICE THAT STARTS WITHOUT WHAT THE
SHELL HAD, OR LEAVES A TOKEN WHERE OTHERS CAN READ IT. A unit that
starts ``samay serve`` but has no SAMAY_YANTRA, no SAMAY_DVARA_URL and
no PATH runs every schedule into "cannot find yantra" at 08:00. So the
settings are carried over -- into a file only its owner can read,
because SAMAY_DVARA_TOKEN is one of them -- and the unit itself holds
none of them, so it can be shown to anybody. And nothing is started:
that is the person's call.
"""

from __future__ import annotations

import stat

import pytest

from samay import unit
from samay.cli import main


@pytest.fixture
def config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("SAMAY_DVARA_TOKEN", "s3cret-token-value")
    monkeypatch.setenv("SAMAY_YANTRA", "/opt/yantra/bin/yantra --provider ollama")
    monkeypatch.setenv("YANTRA_MEMORY", "off")
    monkeypatch.setenv("UNRELATED", "nope")
    return tmp_path / "config"


def test_printing_the_unit_writes_nothing(config, tmp_path, capsys):
    assert main(["--state", str(tmp_path / "s"), "unit"]) == 0
    out = capsys.readouterr().out
    assert "ExecStart=" in out and "serve --port 8780" in out
    assert "Restart=on-failure" in out
    assert not (config / "systemd").exists()


def test_install_carries_the_shells_settings_and_says_what_it_did(config, tmp_path,
                                                                 capsys):
    assert main(["--state", str(tmp_path / "s"), "unit", "--install"]) == 0
    env = (config / "samay" / "samay.env").read_text()
    assert 'SAMAY_YANTRA="/opt/yantra/bin/yantra --provider ollama"' in env
    assert "YANTRA_MEMORY=off" in env and "PATH=" in env
    assert "UNRELATED" not in env
    out = capsys.readouterr().out
    assert "systemctl --user enable --now samay" in out
    assert "s3cret-token-value" not in out          # names, never values


def test_the_env_file_is_its_owners_alone(config, tmp_path):
    main(["--state", str(tmp_path / "s"), "unit", "--install"])
    mode = stat.S_IMODE((config / "samay" / "samay.env").stat().st_mode)
    assert mode == 0o600


def test_an_old_env_file_left_open_is_closed_on_reinstall(config, tmp_path):
    env = config / "samay" / "samay.env"
    env.parent.mkdir(parents=True)
    env.write_text("old\n")
    env.chmod(0o644)
    main(["--state", str(tmp_path / "s"), "unit", "--install"])
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_the_unit_holds_no_setting(config, tmp_path):
    main(["--state", str(tmp_path / "s"), "unit", "--install"])
    text = (config / "systemd" / "user" / "samay.service").read_text()
    assert "s3cret" not in text and "SAMAY_YANTRA" not in text
    assert f"EnvironmentFile=-{config / 'samay' / 'samay.env'}" in text


@pytest.mark.parametrize("value,written", [
    ("plain/path_1.2", "plain/path_1.2"),
    ('has "quotes" and spaces', '"has \\"quotes\\" and spaces"'),
    ("back\\slash", '"back\\\\slash"')])
def test_values_are_quoted_the_way_systemd_reads_them(value, written):
    assert f"SAMAY_X={written}" in unit.env_text({"SAMAY_X": value})
