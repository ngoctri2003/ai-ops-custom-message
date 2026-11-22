"""Machine-to-machine notifications (Atlassian News approval flow).

Only fixed destinations from env can be targeted, so a leaked token cannot be used
to message arbitrary people or channels.
"""
import re

from . import config
from .slack import Slack, SlackError

MAX_NOTIFY_TEXT = 1000
BROADCAST = re.compile(r"<!(channel|here|everyone|subteam)", re.IGNORECASE)
USER_MENTION = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")


def validate(body: dict, allowed_users: set[str], allowed_channels: set[str]) -> tuple[dict | None, list[str]]:
    action = str(body.get("action", ""))
    target = str(body.get("target", ""))
    text = body.get("text")
    errors: list[str] = []
    if action not in ("dm", "channel"):
        errors.append("action must be dm or channel")
    if not isinstance(text, str) or not text.strip():
        errors.append("text is required")
        text = ""
    elif len(text) > MAX_NOTIFY_TEXT:
        errors.append(f"text is longer than {MAX_NOTIFY_TEXT} characters")
    allowed = allowed_users if action == "dm" else allowed_channels
    if action in ("dm", "channel") and target not in allowed:
        errors.append("target is not allowed")
    if BROADCAST.search(text):
        errors.append("broadcast mentions are not allowed")
    for uid in USER_MENTION.findall(text):
        if uid not in allowed_users:
            errors.append("mention of a user that is not allowed")
            break
    if errors:
        return None, errors
    return {"action": action, "target": target, "text": text, "dry_run": bool(body.get("dry_run"))}, []


def deliver(slack: Slack, body: dict) -> tuple[int, dict]:
    clean, errors = validate(body, config.notify_users(), config.notify_channels())
    if errors:
        return 400, {"errors": errors}
    if clean["dry_run"]:
        return 200, {"ok": True, "dry_run": True, "action": clean["action"], "length": len(clean["text"])}
    try:
        channel = clean["target"]
        if clean["action"] == "dm":
            channel = slack.call("conversations.open", {"users": clean["target"]})["channel"]["id"]
        res = slack.call("chat.postMessage", {"channel": channel, "text": clean["text"],
                                              "unfurl_links": False, "unfurl_media": False})
    except SlackError as exc:
        hint = "Invite the AI Ops bot to the channel first." if exc.error in ("not_in_channel", "channel_not_found") else ""
        return 502, {"ok": False, "error": exc.error, "hint": hint}
    return 200, {"ok": True, "ts": res.get("ts")}
