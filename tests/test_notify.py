import pytest

from app import config, notify
from app.slack import SlackError

CH = "C02V9L0NU3D"
U1, U2 = "U03LF1T0RQW", "U07SXEY5K5L"


class FakeSlack:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail

    def call(self, method, params=None):
        self.calls.append((method, params or {}))
        if self.fail:
            raise SlackError(self.fail)
        if method == "conversations.open":
            return {"ok": True, "channel": {"id": "D1"}}
        return {"ok": True, "ts": "1.1"}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("NOTIFY_ALLOWED_USERS", f"{U1},{U2}")
    monkeypatch.setenv("NOTIFY_ALLOWED_CHANNELS", CH)


def body(**kw):
    return {"action": "channel", "target": CH, "text": "hello", **kw}


def test_channel_post_ok():
    s = FakeSlack()
    status, res = notify.deliver(s, body(text=f"hi <@{U1}> <@{U2}>"))
    assert status == 200 and res["ok"]
    assert s.calls[0][0] == "chat.postMessage" and s.calls[0][1]["channel"] == CH
    assert s.calls[0][1]["unfurl_links"] is False


def test_dm_opens_conversation_first():
    s = FakeSlack()
    status, _ = notify.deliver(s, {"action": "dm", "target": U1, "text": "link"})
    assert status == 200
    assert [c[0] for c in s.calls] == ["conversations.open", "chat.postMessage"]
    assert s.calls[1][1]["channel"] == "D1"


@pytest.mark.parametrize("bad", [
    {"action": "dm", "target": "U0OTHER000"},
    {"action": "channel", "target": "C0OTHER000"},
    {"action": "channel", "target": U1},
    {"action": "nope"},
    {"text": ""},
    {"text": "x" * 1001},
    {"text": "<!channel> hi"},
    {"text": "<!here>"},
    {"text": "<!subteam^S123> hi"},
    {"text": "<@U0OTHER000> hi"},
])
def test_rejects_and_sends_nothing(bad):
    s = FakeSlack()
    status, res = notify.deliver(s, body(**bad))
    assert status == 400 and res["errors"] and not s.calls


def test_exactly_1000_chars_ok():
    assert notify.deliver(FakeSlack(), body(text="x" * 1000))[0] == 200


def test_dry_run_sends_nothing():
    s = FakeSlack()
    status, res = notify.deliver(s, body(dry_run=True))
    assert status == 200 and res["dry_run"] and not s.calls


def test_slack_error_returns_502_with_hint():
    status, res = notify.deliver(FakeSlack(fail="not_in_channel"), body())
    assert status == 502 and res["error"] == "not_in_channel" and res["hint"]


def test_unconfigured_allowlists_deny_everything(monkeypatch):
    monkeypatch.delenv("NOTIFY_ALLOWED_CHANNELS")
    monkeypatch.delenv("NOTIFY_ALLOWED_USERS")
    assert notify.deliver(FakeSlack(), body())[0] == 400
    assert config.notify_users() == set()


# ---------- machine auth (web.BaseHandler.serve_machine) ----------
import io
import json as _json

from app import web


class Fake(web.BaseHandler):
    def __init__(self, headers, payload=b"{}"):  # no socket: bypass BaseHTTPRequestHandler init
        self.headers = headers
        self.rfile = io.BytesIO(payload)
        self.out = None

    def _send(self, status, obj, set_cookie=None):
        self.out = (status, obj)


def machine(headers, payload, monkeypatch, fn=None):
    monkeypatch.setenv("NOTIFY_TOKEN", "tok-123")
    monkeypatch.setenv("SLACK_BOT_TOKEN", "xoxb-fake")
    h = Fake({"Content-Length": str(len(payload)), **headers}, payload)
    h.serve_machine(fn or (lambda slack, body, now: (200, {"ok": True})))
    return h.out


def test_machine_requires_token(monkeypatch):
    p = _json.dumps(body()).encode()
    assert machine({}, p, monkeypatch)[0] == 401
    assert machine({"X-Aiops-Token": "wrong"}, p, monkeypatch)[0] == 401
    assert machine({"X-Aiops-Token": "tok-123"}, p, monkeypatch)[0] == 200


def test_machine_fails_closed_when_not_configured(monkeypatch):
    p = b"{}"
    monkeypatch.delenv("NOTIFY_TOKEN", raising=False)
    h = Fake({"Content-Length": "2", "X-Aiops-Token": "x"}, p)
    h.serve_machine(lambda *a: (200, {}))
    assert h.out[0] == 503
    monkeypatch.setenv("NOTIFY_TOKEN", "t")
    monkeypatch.delenv("SLACK_BOT_TOKEN", raising=False)
    h.serve_machine(lambda *a: (200, {}))
    assert h.out[0] == 503


def test_machine_bad_body_and_internal_error(monkeypatch):
    assert machine({"X-Aiops-Token": "tok-123"}, b"[1]", monkeypatch)[0] == 400

    def boom(*a):
        raise RuntimeError("secret detail")
    status, obj = machine({"X-Aiops-Token": "tok-123"}, b"{}", monkeypatch, boom)
    assert status == 500 and obj == {"error": "server_error"}
