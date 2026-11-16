import json
from datetime import datetime, time, timedelta

import pytest

from app import auth, config, planner, routes, web
from app.schedule import next_occurrence, occurrences
from app.slack import SlackError

TZ = config.TZ
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=TZ)  # a Monday


def vn(y, m, d, hh, mm):
    return datetime(y, m, d, hh, mm, tzinfo=TZ)


# ---------- schedule ----------
def test_next_occurrence_rules():
    assert next_occurrence("daily", vn(2026, 11, 16, 8, 0), time(9, 0), TZ) == vn(2026, 11, 16, 9, 0)
    assert next_occurrence("daily", vn(2026, 11, 16, 9, 0), time(9, 0), TZ) == vn(2026, 11, 17, 9, 0)
    assert next_occurrence("weekdays", vn(2026, 11, 20, 10, 0), time(9, 0), TZ) == vn(2026, 11, 23, 9, 0)
    assert next_occurrence("weekly:3", vn(2026, 11, 16, 8, 0), time(14, 0), TZ) == vn(2026, 11, 19, 14, 0)


def test_occurrences_stops_at_until_and_flags_overflow():
    first = vn(2026, 11, 17, 9, 0)
    runs = occurrences("daily", first, vn(2026, 11, 20, 0, 0).date(), time(9, 0), TZ, 60)
    assert [r.day for r in runs] == [17, 18, 19, 20]
    many = occurrences("daily", first, vn(2027, 3, 1, 0, 0).date(), time(9, 0), TZ, 5)
    assert len(many) == 6  # cap + 1 means "too many"


# ---------- auth ----------
def test_password_roundtrip_and_login():
    h = auth.hash_password("correct horse battery", iterations=1000)
    assert auth.verify_password("correct horse battery", h)
    assert not auth.verify_password("wrong", h)
    users = {"tri": h}
    assert auth.verify_login(users, "tri", "correct horse battery")
    assert not auth.verify_login(users, "tri", "nope")
    assert not auth.verify_login(users, "ghost", "correct horse battery")


def test_session_sign_expire_tamper():
    tok = auth.make_session("tri", "secret", now=1000, ttl=60)
    assert auth.read_session(tok, "secret", now=1030) == "tri"
    assert auth.read_session(tok, "secret", now=1061) is None
    assert auth.read_session(tok, "other", now=1030) is None
    assert auth.read_session(tok + "x", "secret", now=1030) is None
    assert auth.read_session("garbage", "secret", now=1030) is None


# ---------- planner ----------
LISTS = {"leader": ["U1", "U2"], "team": ["U2", "U3"]}


def body(**kw):
    base = {"text": "hi", "channels": ["C0123456789"], "when": "now"}
    base.update(kw)
    return planner.normalize(base)


def check(**kw):
    return planner.validate(body(**kw), NOW, LISTS, None)


def test_valid_now():
    errors, runs = check()
    assert errors == {} and runs == []


def test_text_and_targets_required():
    errors, _ = check(text="", channels=[])
    assert set(errors) == {"text", "channels"}


def test_usergroup_and_mention_need_channel():
    errors, _ = check(channels=[], lists=["leader"], usergroups=["S0123456789"], mention="here")
    assert {"usergroups", "mention"} <= set(errors)


def test_bad_ids_and_allowlist():
    assert "channels" in check(channels=["not an id"])[0]
    errors, _ = planner.validate(body(channels=["C0123456789"]), NOW, LISTS, {"C9999999999"})
    assert "channels" in errors


def test_unknown_list_and_recipient_cap(monkeypatch):
    assert "lists" in check(lists=["nope"])[0]
    monkeypatch.setattr(config, "MAX_RECIPIENTS", 2)
    assert "lists" in check(lists=["leader", "team"])[0]  # 3 unique users


def test_schedule_once_rules():
    assert "date" in check(when="schedule", rule="once", time="09:00", date="2026-11-16")[0]
    assert "date" in check(when="schedule", rule="once", time="09:00", date="2027-06-01")[0]
    errors, runs = check(when="schedule", rule="once", time="09:00", date="2026-11-17")
    assert errors == {} and runs == [vn(2026, 11, 17, 9, 0)]
    assert "time" in check(when="schedule", rule="once", date="2026-11-17", time="25:00")[0]


def test_schedule_recurring_rules(monkeypatch):
    errors, runs = check(when="schedule", rule="daily", time="09:00", until="2026-11-20")
    assert errors == {} and len(runs) == 4
    assert "until" in check(when="schedule", rule="daily", time="09:00")[0]
    assert "until" in check(when="schedule", rule="daily", time="09:00", until="2027-12-01")[0]
    monkeypatch.setattr(config, "MAX_OCCURRENCES", 3)
    assert "until" in check(when="schedule", rule="daily", time="09:00", until="2026-11-30")[0]


def test_total_deliveries_cap(monkeypatch):
    monkeypatch.setattr(config, "MAX_DELIVERIES", 5)
    errors, _ = check(when="schedule", rule="daily", time="09:00", until="2026-11-20")  # 1 target x 4 runs
    assert errors == {}
    errors, _ = check(channels=["C0123456789", "C0123456780"], when="schedule", rule="daily",
                      time="09:00", until="2026-11-20")  # 2 x 4 = 8
    assert "channels" in errors


def test_build_text():
    assert planner.build_text("hi", "channel", ["S1"]) == "<!channel> <!subteam^S1>\nhi"
    assert planner.build_text("hi", "none", []) == "hi"


# ---------- routes (fake Slack) ----------
class FakeSlack:
    def __init__(self, fail=None):
        self.calls, self.fail = [], fail or {}

    def call(self, method, params=None):
        params = params or {}
        self.calls.append((method, params))
        key = params.get("channel") or params.get("users")
        if key in self.fail:
            raise SlackError(self.fail[key])
        if method == "conversations.open":
            return {"ok": True, "channel": {"id": "D" + params["users"]}}
        if method == "chat.postMessage":
            return {"ok": True, "ts": "1.1"}
        if method == "chat.scheduleMessage":
            return {"ok": True, "scheduled_message_id": f"Q{len(self.calls)}"}
        return {"ok": True}


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("RECIPIENT_LISTS", json.dumps(LISTS))


def run_send(slack, **kw):
    return routes.send(slack, {"text": "hi", "channels": ["C0123456789"], **kw}, NOW, sleep=lambda s: None)


def test_dry_run_sends_nothing():
    slack = FakeSlack()
    status, res = run_send(slack, dry_run=True, lists=["leader"])
    assert status == 200 and res["preview"]["recipients"] == 2 and slack.calls == []


def test_send_now_partial_failure():
    slack = FakeSlack(fail={"C0123456789": "not_in_channel"})
    status, res = run_send(slack, lists=["leader"])
    assert status == 200 and res["sent"] == 2 and res["total"] == 3 and not res["ok"]
    assert "mời bot" in res["hint"]
    posted = [p["channel"] for m, p in slack.calls if m == "chat.postMessage"]
    assert sorted(posted) == ["C0123456789", "DU1", "DU2"]


def test_validation_errors_return_400_and_send_nothing():
    slack = FakeSlack()
    status, res = run_send(slack, text="")
    assert status == 400 and "text" in res["errors"] and slack.calls == []


def test_schedule_creates_one_message_per_target_per_run():
    slack = FakeSlack()
    status, res = run_send(slack, when="schedule", rule="daily", time="09:00", until="2026-11-19")
    sched = [p for m, p in slack.calls if m == "chat.scheduleMessage"]
    assert status == 200 and len(sched) == 3 and res["total"] == 3
    assert sched[0]["post_at"] == int(vn(2026, 11, 17, 9, 0).timestamp())


def test_dm_open_failure_only_affects_that_user():
    slack = FakeSlack(fail={"U1": "user_not_found"})
    status, res = run_send(slack, channels=[], lists=["leader"])
    assert res["sent"] == 1 and res["total"] == 2
    assert any(r["target"] == "user U1" and not r["ok"] for r in res["results"])


def test_ratelimit_retries_once():
    class Limited(FakeSlack):
        def call(self, method, params=None):
            if method == "chat.postMessage" and not getattr(self, "hit", False):
                self.hit = True
                raise SlackError("ratelimited", 1)
            return super().call(method, params)

    status, res = run_send(Limited())
    assert res["sent"] == 1


def test_cancel_and_scheduled_list():
    slack = FakeSlack()
    assert routes.cancel(slack, {"channel": "C1", "id": "Q1"})[0] == 200
    assert routes.cancel(slack, {})[0] == 400

    class L(FakeSlack):
        def call(self, method, params=None):
            return {"ok": True, "scheduled_messages": [
                {"id": "Q2", "channel_id": "C1", "post_at": 200, "text": "b"},
                {"id": "Q1", "channel_id": "C1", "post_at": 100, "text": "a"}]}

    items = routes.scheduled(L())[1]["items"]
    assert [i["id"] for i in items] == ["Q1", "Q2"]


def test_options_filters_allowed_channels(monkeypatch):
    monkeypatch.setenv("SLACK_ALLOWED_CHANNELS", "C1")

    class O(FakeSlack):
        def call(self, method, params=None):
            if method == "conversations.list":
                return {"ok": True, "channels": [{"id": "C1", "name": "a", "is_member": True},
                                                 {"id": "C2", "name": "b", "is_member": True}]}
            raise SlackError("missing_scope")

    status, res = routes.options(O())
    assert [c["id"] for c in res["channels"]] == ["C1"] and res["usergroups"] == []
    assert res["lists"][0]["name"] == "leader"


# ---------- web glue ----------
def test_login_sets_httponly_cookie(monkeypatch):
    monkeypatch.setenv("AUTH_SECRET", "s")
    monkeypatch.setenv("AUTH_USERS", json.dumps({"tri": auth.hash_password("correct horse battery", iterations=1000)}))
    status, obj, cookie = web.login({"username": "tri", "password": "correct horse battery"}, NOW)
    assert status == 200 and "HttpOnly" in cookie and "SameSite=Strict" in cookie and "Secure" in cookie
    assert web.login({"username": "tri", "password": "x"}, NOW)[0] == 401
