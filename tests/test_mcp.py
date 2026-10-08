"""The agent's tools: offered, accepted, and only ever one person's.

The bias these tests encode: THE MODEL CANNOT ACT FOR ANYONE BUT THE
PERSON THE HARNESS NAMED, AND CANNOT MAKE A SCHEDULE WITHOUT THE PERSON
BEING ASKED. The first is checked directly -- another person's schedule
is "no schedule", to every tool. The second is the harness's job, so
what is checked here is the promise it relies on: the reading tools
say readOnlyHint true and every changing tool says false.

The protocol is checked as a client sees it: a real `samay mcp` process,
newline-delimited JSON-RPC on its stdin and stdout.
"""

from __future__ import annotations

import io
import json
import subprocess
import sys

import pytest

from samay import schedules
from samay.mcp import TOOLS, Tools, answer, serve
from samay.store import Store


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMAY_TZ", "UTC")
    return Store(tmp_path / "samay.sqlite3")


def tools_for(store, tmp_path, person="local", **kw):
    return Tools(store, tmp_path, person=person, **kw)


def call(tools, name, **args):
    reply = answer(tools, {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                           "params": {"name": name, "arguments": args}})
    result = reply["result"]
    return result["isError"], result["content"][0]["text"]


class TestWhatAHarnessReliesOn:
    def test_reading_tools_say_so_and_changing_ones_do_not(self):
        hints = {t["name"]: t["annotations"]["readOnlyHint"] for t in TOOLS}
        assert hints == {"preview_schedule": True, "list_schedules": True,
                         "schedule_runs": True, "create_schedule": False,
                         "pause_schedule": False, "resume_schedule": False,
                         "delete_schedule": False}

    def test_only_delete_is_destructive(self):
        destroys = {t["name"] for t in TOOLS
                    if t["annotations"].get("destructiveHint")}
        assert destroys == {"delete_schedule"}

    def test_there_is_no_way_to_name_another_person(self):
        for tool in TOOLS:
            props = tool["inputSchema"].get("properties", {})
            assert not {"owner", "for", "as", "person", "agent",
                        "runner"} & set(props), tool["name"]

    def test_no_run_now_from_inside_a_turn(self):
        assert not any("run" in t["name"] and "runs" not in t["name"]
                       for t in TOOLS)


class TestTheTools:
    def test_preview_then_create(self, store, tmp_path):
        tools = tools_for(store, tmp_path, agent="")
        err, said = call(tools, "preview_schedule", when={"at": "08:00"})
        assert not err and said.startswith("every day at 08:00 -- next:")
        err, saved = call(tools, "create_schedule", prompt="check my mail",
                          when={"at": "08:00"}, allow_tools=["browser_*"])
        assert not err and saved.startswith("Saved ")
        assert "clock is not running" in saved     # and it says so
        (made,) = store.schedules()
        assert made.created_via == "agent" and made.owner == "local"
        assert made.allow_tools == ["browser_*"] and made.runner == "direct"

    def test_the_agent_and_road_are_the_harness_s_not_the_model_s(
            self, store, tmp_path):
        pkg = tmp_path / "mail"
        pkg.mkdir()
        (pkg / "agent.toml").write_text("")
        tools = tools_for(store, tmp_path, agent=str(pkg))
        call(tools, "create_schedule", prompt="p", when={"every": "2h"},
             agent="/somewhere/else")
        assert store.schedules()[0].agent == str(pkg)

    def test_a_mistake_is_an_error_the_model_can_read(self, store, tmp_path):
        err, said = call(tools_for(store, tmp_path), "create_schedule",
                         prompt="p", when={"every": "1m"})
        assert err and "too often" in said

    def test_another_persons_schedule_is_no_schedule(self, store, tmp_path):
        theirs = schedules.create(store, prompt="their mail", when="every 2h",
                                  owner="priya")
        mine = tools_for(store, tmp_path, person="mahen")
        for name in ("pause_schedule", "resume_schedule", "delete_schedule",
                     "schedule_runs"):
            err, said = call(mine, name, id=theirs.id)
            assert err and "no schedule" in said, name
        assert call(mine, "list_schedules")[1] == "No schedules yet."
        assert store.get(theirs.id).state == "active"

    def test_pause_resume_delete_and_runs(self, store, tmp_path):
        tools = tools_for(store, tmp_path)
        call(tools, "create_schedule", prompt="p", when={"every": "2h"})
        sid = store.schedules()[0].id
        assert call(tools, "pause_schedule", id=sid)[1] == f"Paused {sid}."
        assert call(tools, "resume_schedule", id=sid)[1].startswith(f"Resumed {sid}")
        assert call(tools, "schedule_runs", id=sid)[1] == f"{sid} has not run yet."
        assert "every 2 hours" in call(tools, "list_schedules")[1]
        assert call(tools, "delete_schedule", id=sid)[1].startswith(f"Deleted {sid}")
        assert store.schedules() == []

    def test_an_unknown_tool_is_an_error(self, store, tmp_path):
        err, said = call(tools_for(store, tmp_path), "_mine", id="x")
        assert err and "no tool" in said


class TestTheProtocol:
    def test_initialize_agrees_on_a_version_it_speaks(self, store, tmp_path):
        tools = tools_for(store, tmp_path)
        reply = answer(tools, {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                               "params": {"protocolVersion": "2025-03-26"}})
        assert reply["result"]["protocolVersion"] == "2025-03-26"
        reply = answer(tools, {"jsonrpc": "2.0", "id": 2, "method": "initialize",
                               "params": {"protocolVersion": "1999-01-01"}})
        assert reply["result"]["protocolVersion"] == "2025-06-18"

    def test_notifications_get_no_reply_and_unknown_methods_an_error(
            self, store, tmp_path):
        tools = tools_for(store, tmp_path)
        assert answer(tools, {"jsonrpc": "2.0",
                              "method": "notifications/initialized"}) is None
        reply = answer(tools, {"jsonrpc": "2.0", "id": 3, "method": "nope"})
        assert reply["error"]["code"] == -32601

    def test_a_line_that_is_not_json_is_answered_not_fatal(self, store, tmp_path):
        out = io.StringIO()
        serve(tools_for(store, tmp_path),
              io.StringIO('{oops\n{"jsonrpc":"2.0","id":1,"method":"ping"}\n'), out)
        first, second = [json.loads(line) for line in out.getvalue().splitlines()]
        assert first["error"]["code"] == -32700 and second["result"] == {}

    def test_a_real_process_end_to_end(self, tmp_path):
        lines = [
            {"jsonrpc": "2.0", "id": 1, "method": "initialize",
             "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                        "clientInfo": {"name": "test", "version": "0"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
             "params": {"name": "create_schedule",
                        "arguments": {"prompt": "check", "when": {"every": "3h"}}}},
        ]
        done = subprocess.run(
            [sys.executable, "-m", "samay.cli", "--state", str(tmp_path),
             "mcp", "--for", "local"],
            input="".join(json.dumps(m) + "\n" for m in lines),
            capture_output=True, text=True, timeout=30,
            env={"SAMAY_TZ": "UTC", "PATH": "/usr/bin:/bin"})
        replies = [json.loads(line) for line in done.stdout.splitlines()]
        assert [r["id"] for r in replies] == [1, 2, 3]
        assert len(replies[1]["result"]["tools"]) == 7
        assert replies[2]["result"]["content"][0]["text"].startswith("Saved ")
        assert len(Store(tmp_path / "samay.sqlite3").schedules()) == 1


def test_a_turn_with_the_phone_makes_schedules_that_work_it(store, tmp_path):
    """--phone (from Dvara): a schedule made here is a phone schedule --
    on the direct road, which has no phone, that is said, not saved."""
    with_phone = tools_for(store, tmp_path, phone=True)
    failed, said = call(with_phone, "create_schedule", prompt="p", when="every 1h",
                        phone_steps=["send in Messages when the screen shows 555-0123"])
    assert failed and "Dvara road" in said
    assert with_phone.phone and not tools_for(store, tmp_path).phone
