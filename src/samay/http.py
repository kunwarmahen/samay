"""Samay's page, and the JSON behind it -- served by ``samay serve``.

A person who set something to run every two hours wants to see it
without opening a terminal: what is set up, when it next runs, what the
last run said, and a button to stop it. ``samay serve`` already runs the
clock; it now also serves one page, and the small JSON API the page is
drawn from (which any other program may use too):

    GET    /api/status
    GET    /api/schedules                 every schedule, with its last run
    GET    /api/schedules/ID
    GET    /api/runs?schedule=ID&limit=N  newest first
    POST   /api/preview      {when, tz}   the sentence, before anything is saved
    POST   /api/schedules    {prompt, when, ...}
    POST   /api/schedules/ID/pause | /resume | /run
    DELETE /api/schedules/ID

A TOKEN, ALWAYS. Every ``/api`` call carries ``Authorization: Bearer``.
Localhost is not a boundary: any web page you visit can send a request
to 127.0.0.1, and without a token one of them could delete your
schedules or add one that runs every five minutes. The token is
``$SAMAY_TOKEN``, or one Samay makes once and keeps in the state folder
(readable by you alone). ``samay serve`` prints the page's address with
the token after a ``#`` -- the part of an address a browser never sends
to a server, so it is in no log -- and the page keeps it for next time.

THE PAGE ITSELF NEEDS NO TOKEN. It is one static file with no data in
it; everything it shows, it asks the API for. No CORS headers are sent,
so a page on another site cannot read an answer even if it could send
a request -- and it cannot send one with the token, which it does not
have.

LOCALHOST BY DEFAULT, deliberately; reaching the network is a decision
(``--host``), as it is for Dvara.

A RUN STARTED FROM THE PAGE IS NOT WAITED FOR. It can take minutes; the
request answers ``202`` at once and the page sees the run appear.

Standard library only, like the rest of Samay.
"""

from __future__ import annotations

import hmac
import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from samay import schedules
from samay.clock import Clock
from samay.dvara import Dvara
from samay.status import report
from samay.store import Store

#: The largest request body read. A schedule is a prompt and a few
#: fields; anything bigger is not one.
MAX_BODY = 64 * 1024

DEFAULT_PORT = 8780


def serve_token(state: Path) -> str:
    """``$SAMAY_TOKEN``, or the one kept in the state folder (made once)."""
    configured = os.environ.get("SAMAY_TOKEN", "").strip()
    if configured:
        if len(configured) < 16:
            raise ValueError("SAMAY_TOKEN must be at least 16 characters")
        return configured
    path = state / "serve.token"
    try:
        kept = path.read_text().strip()
        if len(kept) >= 16:
            return kept
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(token + "\n")
    return token


class ApiError(Exception):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(detail)
        self.status = status
        self.detail = detail


class Api:
    """What each endpoint does, apart from HTTP -- so tests can call it
    straight, and the handler below stays a thin skin."""

    def __init__(self, store: Store, clock: Clock, state: Path,
                 dvara: Dvara | None = None) -> None:
        self.store = store
        self.clock = clock
        self.state = state
        self.dvara = dvara

    def handle(self, method: str, path: str, query: dict, body: dict
               ) -> tuple[int, dict]:
        parts = [p for p in path.split("/") if p][1:]      # after "api"
        try:
            return self._route(method, parts, query, body)
        except schedules.ScheduleError as exc:
            message = str(exc)
            status = 404 if message.startswith("no schedule") else 400
            raise ApiError(status, message) from None

    def _route(self, method, parts, query, body) -> tuple[int, dict]:
        if parts == ["status"] and method == "GET":
            return 200, report(self.state, self.store)
        if parts == ["preview"] and method == "POST":
            return 200, schedules.preview(_need(body, "when"), body.get("tz"))
        if parts == ["runs"] and method == "GET":
            limit = _int(query.get("limit", ["50"])[0], "limit")
            schedule_id = query.get("schedule", [None])[0]
            if schedule_id:
                schedule_id = schedules.find(self.store, schedule_id).id
            runs = self.store.runs(schedule_id, limit=min(limit, 500))
            return 200, {"runs": [r.as_dict() for r in runs]}
        if parts == ["schedules"]:
            if method == "GET":
                return 200, {"schedules": [schedules.card(s, self.store)
                                           for s in self.store.schedules()]}
            if method == "POST":
                return 201, schedules.card(self._create(body), self.store)
        if len(parts) >= 2 and parts[0] == "schedules":
            schedule = schedules.find(self.store, parts[1])
            action = parts[2] if len(parts) == 3 else None
            if len(parts) == 2 and method == "GET":
                return 200, schedules.card(schedule, self.store)
            if len(parts) == 2 and method == "DELETE":
                schedules.remove(self.store, schedule.id)
                return 200, {"removed": schedule.id}
            if method == "POST" and action == "pause":
                return 200, schedules.card(
                    schedules.pause(self.store, schedule.id), self.store)
            if method == "POST" and action == "resume":
                return 200, schedules.card(
                    schedules.resume(self.store, schedule.id), self.store)
            if method == "POST" and action == "run":
                try:
                    self.clock.start_now(schedule.id)
                except RuntimeError as exc:
                    raise ApiError(409, str(exc)) from None
                return 202, {"started": schedule.id}
        raise ApiError(404, f"no such endpoint: {method} /api/{'/'.join(parts)}")

    def _create(self, body: dict):
        runner = body.get("runner") or "direct"
        allow = body.get("allow_tools") or []
        if isinstance(allow, str):
            allow = [g for g in (p.strip() for p in allow.split(",")) if g]
        if not isinstance(allow, list):
            raise ApiError(400, "allow_tools is a list of tool-name globs")
        return schedules.create(
            self.store, prompt=str(body.get("prompt") or ""),
            when=_need(body, "when"), tz=body.get("tz") or None,
            runner=runner, agent=str(body.get("agent") or ""),
            owner=str(body.get("as") or schedules.LOCAL_OWNER),
            notify=str(body.get("notify") or "when_new"),
            allow_tools=[str(g) for g in allow],
            time_limit=_int(body.get("time_limit")
                            or schedules.DEFAULT_TIME_LIMIT, "time_limit"),
            browser_profile=str(body.get("browser_profile") or ""),
            created_via="page", dvara=self.dvara if runner == "dvara" else None)


def _need(body: dict, key: str):
    value = body.get(key)
    if value in (None, "", {}):
        raise ApiError(400, f"missing: {key}")
    return value


def _int(value, name: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ApiError(400, f"{name} must be a whole number") from None


def page() -> bytes:
    return files("samay").joinpath("static/index.html").read_bytes()


class SamayServer:
    """The API and the page, on a thread of their own beside the clock."""

    def __init__(self, api: Api, token: str, *, host: str = "127.0.0.1",
                 port: int = DEFAULT_PORT) -> None:
        self.api = api
        self.token = token
        handler = _handler(self)
        self.httpd = ThreadingHTTPServer((host, port), handler)
        self.httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}/"

    @property
    def page_url(self) -> str:
        return f"{self.url}#token={self.token}"

    def start(self) -> None:
        self._thread = threading.Thread(target=self.httpd.serve_forever,
                                        name="samay-http", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
        if self._thread is not None:
            self._thread.join()


def _handler(server: SamayServer):
    class Handler(BaseHTTPRequestHandler):
        server_version = "samay"

        def log_message(self, *args):        # the clock's log is the log
            pass

        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, status: int, data: dict) -> None:
            self._send(status, json.dumps(data).encode(), "application/json")

        def _authorized(self) -> bool:
            offered = self.headers.get("Authorization", "")
            want = f"Bearer {server.token}"
            return hmac.compare_digest(offered.encode(), want.encode())

        def _dispatch(self, method: str) -> None:
            url = urlparse(self.path)
            if method == "GET" and url.path in ("/", "/index.html"):
                return self._send(200, page(), "text/html; charset=utf-8")
            if not url.path.startswith("/api/"):
                return self._json(404, {"detail": "not found"})
            if not self._authorized():
                return self._json(401, {"detail": "missing or wrong token"})
            body: dict = {}
            if method == "POST":
                size = int(self.headers.get("Content-Length") or 0)
                if size > MAX_BODY:
                    return self._json(413, {"detail": "request too large"})
                raw = self.rfile.read(size) if size else b""
                try:
                    body = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return self._json(400, {"detail": "the body is not JSON"})
                if not isinstance(body, dict):
                    return self._json(400, {"detail": "the body is a JSON object"})
            try:
                status, data = server.api.handle(
                    method, url.path, parse_qs(url.query), body)
            except ApiError as exc:
                return self._json(exc.status, {"detail": exc.detail})
            except Exception as exc:     # a bug is a 500 that says what, not a hang
                return self._json(500, {"detail": f"{type(exc).__name__}: {exc}"})
            self._json(status, data)

        def do_GET(self):
            self._dispatch("GET")

        def do_POST(self):
            self._dispatch("POST")

        def do_DELETE(self):
            self._dispatch("DELETE")

    return Handler
