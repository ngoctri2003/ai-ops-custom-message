"""HTTP glue for Vercel Python functions (BaseHTTPRequestHandler style)."""
import json
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler

from . import auth, config, routes
from .slack import Slack

CSRF_HEADER = ("X-Requested-With", "aiops-web")
MAX_BODY = 64 * 1024
COOKIE = "session"


def _cookie(token: str, max_age: int) -> str:
    return f"{COOKIE}={token}; Max-Age={max_age}; Path=/; HttpOnly; Secure; SameSite=Strict"


class BaseHandler(BaseHTTPRequestHandler):
    """Subclass and call self.serve(fn, ...) from do_GET / do_POST."""

    def _send(self, status: int, obj: dict, set_cookie: str | None = None) -> None:
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _session_user(self) -> str | None:
        secret = config.auth_secret()
        if not secret:
            return None
        for part in (self.headers.get("Cookie") or "").split(";"):
            name, _, value = part.strip().partition("=")
            if name == COOKIE:
                return auth.read_session(value, secret, int(time.time()))
        return None

    def _body(self) -> dict | None:
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            return None
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            return None
        return data if isinstance(data, dict) else None

    def serve(self, fn, *, post: bool, public: bool = False) -> None:
        """fn(slack, body, now) -> (status, obj). Fails closed when auth or token is not configured."""
        try:
            if not (config.auth_secret() and config.auth_users()):
                return self._send(503, {"error": "not_configured"})
            if post and self.headers.get(CSRF_HEADER[0]) != CSRF_HEADER[1]:
                return self._send(403, {"error": "bad_request"})
            body = {}
            if post:
                body = self._body()
                if body is None:
                    return self._send(400, {"error": "bad_body"})
            if public:
                status, obj, cookie = fn(body, datetime.now(config.TZ))
                return self._send(status, obj, cookie)
            if not self._session_user():
                return self._send(401, {"error": "login_required"})
            token = config.bot_token()
            if not token:
                return self._send(503, {"error": "not_configured"})
            status, obj = fn(Slack(token), body, datetime.now(config.TZ))
            return self._send(status, obj)
        except Exception:  # noqa: BLE001  (never leak internals)
            return self._send(500, {"error": "server_error"})

    def log_message(self, *args):  # keep platform logs free of request details
        pass


def login(body: dict, now: datetime) -> tuple[int, dict, str | None]:
    users, secret = config.auth_users(), config.auth_secret()
    username, password = str(body.get("username", "")), str(body.get("password", ""))
    if not auth.verify_login(users, username, password):
        return 401, {"error": "invalid_credentials"}, None
    token = auth.make_session(username, secret, int(time.time()), config.SESSION_SECONDS)
    return 200, {"user": username}, _cookie(token, config.SESSION_SECONDS)


def logout(body: dict, now: datetime) -> tuple[int, dict, str | None]:
    return 200, {"ok": True}, _cookie("", 0)


# Thin adapters so every route has the (slack, body, now) signature.
def r_options(slack, body, now):
    return routes.options(slack)


def r_send(slack, body, now):
    return routes.send(slack, body, now)


def r_scheduled(slack, body, now):
    return routes.scheduled(slack)


def r_cancel(slack, body, now):
    return routes.cancel(slack, body)
