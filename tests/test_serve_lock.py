"""Is the clock running? Asked of a lock, not of a pid.

The bias these tests encode: A STALE ANSWER NEVER STOPS THE CLOCK, AND A
LIVE ONE IS NEVER MISSED. A serve.json left behind by a crash says
nothing, even when its pid is alive -- in a fresh container the old
number is often the new process itself; a clock held by another process
is seen, from whatever process asks; and it is free again the moment
its holder dies, however it dies.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

from samay.status import hold_clock, serving

HOLDER = """
import sys, time
from pathlib import Path
from samay.status import hold_clock
held = hold_clock(Path(sys.argv[1]))
print("held" if held else "refused", flush=True)
time.sleep(60)
"""


def holder(state):
    proc = subprocess.Popen([sys.executable, "-c", HOLDER, str(state)],
                            stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    return proc


def stop(proc):
    proc.kill()
    proc.wait()
    proc.stdout.close()


def test_a_stale_file_naming_a_live_pid_is_not_a_running_clock(tmp_path):
    (tmp_path / "serve.json").write_text(json.dumps({"pid": os.getpid(), "url": "x"}))
    (tmp_path / "serve.lock").touch()
    assert serving(tmp_path) is None
    held = hold_clock(tmp_path)
    assert held is not None
    held.close()


def test_a_clock_held_elsewhere_is_seen_and_not_taken_twice(tmp_path):
    proc = holder(tmp_path)
    try:
        (tmp_path / "serve.json").write_text(json.dumps({"pid": 1, "url": "http://h/"}))
        assert serving(tmp_path) == {"pid": 1, "url": "http://h/"}
        assert hold_clock(tmp_path) is None
    finally:
        stop(proc)


def test_the_clock_is_free_the_moment_its_holder_dies(tmp_path):
    stop(holder(tmp_path))
    deadline = time.monotonic() + 5
    while serving(tmp_path) is not None and time.monotonic() < deadline:
        time.sleep(0.05)
    assert serving(tmp_path) is None
    held = hold_clock(tmp_path)
    assert held is not None
    held.close()


def test_a_state_folder_that_never_served_is_not_serving(tmp_path):
    assert serving(tmp_path) is None


def test_where_answers_go_is_the_running_clocks_not_the_askers(tmp_path, monkeypatch):
    # Yantra's page asks `samay status` with its own environment, which
    # has no SAMAY_DVARA_*; the clock that sends wrote down its own.
    from samay.status import report
    from samay.store import Store
    monkeypatch.delenv("SAMAY_DVARA_URL", raising=False)
    proc = holder(tmp_path)
    try:
        (tmp_path / "serve.json").write_text(json.dumps(
            {"pid": 1, "url": None, "dvara": "http://dvara:8765", "local_to": "mahen"}))
        said = report(tmp_path, Store(tmp_path / "samay.db"))
        assert said["dvara"] == "http://dvara:8765" and said["local_to"] == "mahen"
    finally:
        stop(proc)
    said = report(tmp_path, Store(tmp_path / "samay2.db"))
    assert said["dvara"] is None and said["local_to"] == ""
