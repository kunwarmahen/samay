"""The page's API: everything the page can do, and nothing without the token.

The bias these tests encode: LOCALHOST IS NOT A BOUNDARY. Any page the
person visits can send a request to 127.0.0.1, so every /api call
without the exact token is refused -- and the page itself, which holds
no data, is the only thing served without one. Beyond that: a mistake
in a request is a 4xx that says what to fix, and a run started from the
page answers at once rather than holding the request for minutes.

A real server on a free port, driven with urllib, so the tests cover
the bytes a browser would send and get back.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from datetime import timedelta

import pytest

from samay import schedules
from samay.clock import Clock
from samay.http import Api, SamayServer, public_address, serve_token
from samay.runners import RunResult
from samay.store import Store, now_utc

TOKEN = "a-token-long-enough-to-be-real"


class SlowRunner:
    def __init__(self) -> None:
        self.release = threading.Event()

    def run(self, schedule, prompt):
        self.release.wait(5)
        return RunResult(ok=True, text="done")


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv("SAMAY_TZ", "UTC")
    store = Store(tmp_path / "samay.sqlite3")
    runner = SlowRunner()
    clock = Clock(store, {"direct": runner})
    server = SamayServer(Api(store, clock, tmp_path), TOKEN, port=0)
    server.start()
    server.store, server.runner = store, runner
    yield server
    runner.release.set()
    server.stop()
    clock.close()


def call(server, method, path, body=None, token=TOKEN):
    request = urllib.request.Request(
        server.url.rstrip("/") + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}"} if token else {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")


def add(server, **kw):
    status, card = call(server, "POST", "/api/schedules",
                        {"prompt": "check my mail", "when": "every 2h", **kw})
    assert status == 201, card
    return card


class TestTheToken:
    def test_the_page_needs_none_and_holds_no_data(self, site):
        add(site, prompt="water the ferns on the balcony")
        with urllib.request.urlopen(site.url, timeout=10) as response:
            page = response.read().decode()
            assert response.headers["Content-Type"].startswith("text/html")
        assert "<title>Samay</title>" in page
        assert "ferns" not in page

    def test_the_icon_needs_none_either(self, site):
        with urllib.request.urlopen(site.url.rstrip("/") + "/favicon.svg", timeout=10) as response:
            assert response.headers["Content-Type"] == "image/svg+xml"
            assert response.read().startswith(b"<svg")

    @pytest.mark.parametrize("token", [None, "wrong-token-of-enough-length"])
    def test_every_api_call_without_it_is_refused(self, site, token):
        add(site)
        for method, path in (("GET", "/api/schedules"), ("GET", "/api/status"),
                             ("POST", "/api/schedules"),
                             ("DELETE", f"/api/schedules/{site.store.schedules()[0].id}")):
            status, _ = call(site, method, path, body={} if method == "POST" else None,
                             token=token)
            assert status == 401
        assert len(site.store.schedules()) == 1

    def test_no_cross_site_reading_is_offered(self, site):
        with urllib.request.urlopen(site.url, timeout=10) as response:
            assert "Access-Control-Allow-Origin" not in response.headers

    def test_a_token_is_made_once_and_kept_private(self, tmp_path, monkeypatch):
        monkeypatch.delenv("SAMAY_TOKEN", raising=False)
        first = serve_token(tmp_path)
        assert serve_token(tmp_path) == first and len(first) >= 16
        assert (tmp_path / "serve.token").stat().st_mode & 0o777 == 0o600

    def test_a_short_configured_token_is_refused(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SAMAY_TOKEN", "short")
        with pytest.raises(ValueError, match="16"):
            serve_token(tmp_path)


class TestWhatThePageDoes:
    def test_preview_says_it_in_words(self, site):
        status, said = call(site, "POST", "/api/preview", {"when": "at 08:00"})
        assert status == 200 and said["sentence"].startswith("every day at 08:00")

    def test_a_mistake_is_a_400_that_says_what_to_fix(self, site):
        status, body = call(site, "POST", "/api/schedules",
                            {"prompt": "x", "when": "every 1m"})
        assert status == 400 and "too often" in body["detail"]
        status, body = call(site, "POST", "/api/schedules", {"prompt": "x"})
        assert status == 400 and body["detail"] == "missing: when"

    def test_add_list_and_the_day_ahead(self, site):
        card = add(site, allow_tools="browser_*, web_fetch")
        assert card["created_via"] == "page"
        assert card["allow_tools"] == ["browser_*", "web_fetch"]
        status, listed = call(site, "GET", "/api/schedules")
        (only,) = listed["schedules"]
        assert only["sentence"].startswith("every 2 hours")
        # Every two hours: twelve times in the next day.
        assert len(only["upcoming"]) == 12

    def test_pause_resume_delete(self, site):
        card = add(site)
        assert call(site, "POST", f"/api/schedules/{card['id']}/pause")[1]["state"] == "paused"
        assert call(site, "GET", f"/api/schedules/{card['id']}")[1]["upcoming"] == []
        assert call(site, "POST", f"/api/schedules/{card['id']}/resume")[1]["state"] == "active"
        assert call(site, "DELETE", f"/api/schedules/{card['id']}")[0] == 200
        assert call(site, "GET", f"/api/schedules/{card['id']}")[0] == 404

    def test_run_now_answers_at_once_and_twice_is_a_conflict(self, site):
        card = add(site)
        started = time.monotonic()
        status, body = call(site, "POST", f"/api/schedules/{card['id']}/run")
        assert status == 202 and time.monotonic() - started < 2
        status, body = call(site, "POST", f"/api/schedules/{card['id']}/run")
        assert status == 409 and "running already" in body["detail"]
        site.runner.release.set()
        for _ in range(50):
            runs = call(site, "GET", f"/api/runs?schedule={card['id']}")[1]["runs"]
            if runs and runs[0]["outcome"] == "ok":
                break
            time.sleep(0.1)
        assert runs[0]["outcome"] == "ok"

    def test_status_says_whether_the_clock_runs(self, site):
        status, said = call(site, "GET", "/api/status")
        assert status == 200 and said["format"] == "samay.status.v1"
        assert said["serving"] is False        # no serve.json in this test

    def test_an_unknown_endpoint_is_a_404(self, site):
        assert call(site, "GET", "/api/nothing")[0] == 404

    def test_a_body_that_is_not_json_is_a_400(self, site):
        request = urllib.request.Request(
            site.url + "api/schedules", data=b"{not json", method="POST",
            headers={"Authorization": f"Bearer {TOKEN}"})
        with pytest.raises(urllib.error.HTTPError) as exc:
            urllib.request.urlopen(request, timeout=10)
        assert exc.value.code == 400
        exc.value.close()


class TestTheDayAhead:
    def test_only_the_next_day_and_only_when_active(self, tmp_path):
        store = Store(tmp_path / "s.sqlite3")
        made = schedules.create(store, prompt="p", when="every 5h", tz="UTC",
                                now=now_utc() - timedelta(minutes=1))
        times = schedules.card(made)["upcoming"]
        assert 4 <= len(times) <= 5


class TestTheAddressABrowserOpens:
    """Bound is not reached. From a container Samay binds 0.0.0.0, and the
    link it printed -- and that Yantra's Schedules panel opened -- went
    to an address no browser can use."""

    def server(self, tmp_path, monkeypatch, **kw):
        monkeypatch.delenv("SAMAY_PUBLIC_URL", raising=False)
        store = Store(tmp_path / "s.sqlite3")
        clock = Clock(store, {})
        server = SamayServer(Api(store, clock, tmp_path), TOKEN, port=0, **kw)
        return server, clock

    def test_every_address_is_reached_here_at_localhost(self, tmp_path, monkeypatch):
        server, clock = self.server(tmp_path, monkeypatch, host="0.0.0.0")
        try:
            assert server.url.startswith("http://127.0.0.1:")
        finally:
            server.httpd.server_close()
            clock.close()

    def test_a_public_address_is_what_it_says(self, tmp_path, monkeypatch):
        server, clock = self.server(tmp_path, monkeypatch, host="0.0.0.0",
                                    public_url="http://127.0.0.1:18780")
        try:
            assert server.url == "http://127.0.0.1:18780/"
            assert server.page_url == f"http://127.0.0.1:18780/#token={TOKEN}"
        finally:
            server.httpd.server_close()
            clock.close()

    def test_the_environment_can_say_it(self, tmp_path, monkeypatch):
        store = Store(tmp_path / "s.sqlite3")
        clock = Clock(store, {})
        monkeypatch.setenv("SAMAY_PUBLIC_URL", "https://samay.example/")
        server = SamayServer(Api(store, clock, tmp_path), TOKEN, port=0)
        try:
            assert server.url == "https://samay.example/"
        finally:
            server.httpd.server_close()
            clock.close()

    @pytest.mark.parametrize("bad", ["samay.example", "ftp://x/", "http://"])
    def test_an_address_a_browser_cannot_open_is_refused(self, bad):
        with pytest.raises(ValueError):
            public_address(bad)
