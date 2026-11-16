"""Route logic. Each function returns (http_status, json_body). Slack is the only datastore."""
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import config
from .planner import build_text, normalize, recipients_of, validate
from .schedule import RULE_LABELS
from .slack import Slack, SlackError


def _call(slack: Slack, method: str, params: dict, sleep=time.sleep) -> dict:
    try:
        return slack.call(method, params)
    except SlackError as exc:
        if exc.error != "ratelimited":
            raise
        sleep(min(exc.retry_after or 1, 5))
        return slack.call(method, params)


def options(slack: Slack) -> tuple[int, dict]:
    allowed = config.allowed_channels()
    channels, cursor = [], None
    for _ in range(5):
        res = _call(slack, "conversations.list", {
            "types": "public_channel,private_channel", "exclude_archived": "true",
            "limit": 200, "cursor": cursor})
        for c in res.get("channels", []):
            if allowed is not None and c["id"] not in allowed:
                continue
            channels.append({"id": c["id"], "name": c.get("name", c["id"]),
                             "private": bool(c.get("is_private")), "member": bool(c.get("is_member"))})
        cursor = (res.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    channels.sort(key=lambda c: c["name"])
    try:
        groups = [{"id": g["id"], "handle": g["handle"]}
                  for g in _call(slack, "usergroups.list", {}).get("usergroups", [])]
    except SlackError:
        groups = []  # scope usergroups:read missing
    lists = config.recipient_lists()
    return 200, {"channels": channels, "usergroups": groups,
                 "lists": [{"name": n, "count": len(u)} for n, u in sorted(lists.items())],
                 "rules": RULE_LABELS}


def _preview(s: dict, runs: list[datetime], recipients: list[str]) -> dict:
    return {
        "text": s["text"], "channel_text": build_text(s["text"], s["mention"], s["usergroups"]),
        "channels": s["channels"], "usergroups": s["usergroups"], "lists": s["lists"],
        "recipients": len(recipients), "mention": s["mention"], "when": s["when"],
        "rule": s["rule"], "run_count": len(runs),
        "runs": [r.strftime("%d/%m/%Y %H:%M") for r in runs[:5]],
    }


def send(slack: Slack, body: dict, now: datetime, sleep=time.sleep) -> tuple[int, dict]:
    s = normalize(body)
    lists = config.recipient_lists()
    errors, runs = validate(s, now, lists, config.allowed_channels())
    if errors:
        return 400, {"errors": errors}
    recipients = recipients_of(s["lists"], lists)
    preview = _preview(s, runs, recipients)
    if s["dry_run"]:
        return 200, {"ok": True, "preview": preview}

    # Resolve DM channels first, so a failure only affects that user.
    results: list[dict] = []
    deliveries: list[tuple[str, str, str]] = []
    channel_text = preview["channel_text"]
    for c in s["channels"]:
        deliveries.append((f"channel {c}", c, channel_text))

    def open_dm(uid):
        try:
            return uid, _call(slack, "conversations.open", {"users": uid}, sleep)["channel"]["id"], ""
        except SlackError as exc:
            return uid, None, exc.error

    with ThreadPoolExecutor(config.WORKERS) as pool:
        for uid, dm, err in pool.map(open_dm, recipients):
            if dm:
                deliveries.append((f"user {uid}", dm, s["text"]))
            else:
                results.append({"target": f"user {uid}", "run": None, "ok": False, "error": err})

    tasks = [(t, ch, text, run) for t, ch, text in deliveries for run in (runs or [None])]

    def do(task):
        target, channel, text, run = task
        try:
            if run is None:
                res = _call(slack, "chat.postMessage", {"channel": channel, "text": text}, sleep)
                return {"target": target, "run": None, "ok": True, "error": "", "id": res.get("ts")}
            res = _call(slack, "chat.scheduleMessage",
                        {"channel": channel, "text": text, "post_at": int(run.timestamp())}, sleep)
            return {"target": target, "run": run.strftime("%d/%m/%Y %H:%M"), "ok": True, "error": "",
                    "id": res.get("scheduled_message_id")}
        except SlackError as exc:
            return {"target": target, "run": run.strftime("%d/%m/%Y %H:%M") if run else None,
                    "ok": False, "error": exc.error}

    with ThreadPoolExecutor(config.WORKERS) as pool:
        results.extend(pool.map(do, tasks))
    ok = sum(1 for r in results if r["ok"])
    hint = ""
    if any(r["error"] in ("not_in_channel", "channel_not_found") for r in results if not r["ok"]):
        hint = "Channel riêng cần mời bot AI Ops vào trước."
    return 200, {"ok": ok == len(results), "sent": ok, "total": len(results), "hint": hint, "results": results}


def scheduled(slack: Slack) -> tuple[int, dict]:
    items, cursor = [], None
    for _ in range(3):
        res = _call(slack, "chat.scheduledMessages.list", {"limit": 100, "cursor": cursor})
        for m in res.get("scheduled_messages", []):
            items.append({"id": m["id"], "channel": m["channel_id"], "post_at": m["post_at"],
                          "when": datetime.fromtimestamp(m["post_at"], config.TZ).strftime("%d/%m/%Y %H:%M"),
                          "text": (m.get("text") or "")[:160]})
        cursor = (res.get("response_metadata") or {}).get("next_cursor")
        if not cursor:
            break
    items.sort(key=lambda m: m["post_at"])
    return 200, {"items": items}


def cancel(slack: Slack, body: dict) -> tuple[int, dict]:
    channel, sid = str(body.get("channel", "")), str(body.get("id", ""))
    if not channel or not sid:
        return 400, {"error": "missing_fields"}
    try:
        _call(slack, "chat.deleteScheduledMessage", {"channel": channel, "scheduled_message_id": sid})
    except SlackError as exc:
        return 400, {"error": exc.error}
    return 200, {"ok": True}
