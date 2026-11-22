"""Configuration. Everything secret or environment-specific comes from env vars."""
import json
import os
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Ho_Chi_Minh")

MAX_TEXT = 3500
MAX_CHANNELS = 10
MAX_RECIPIENTS = 50
MAX_OCCURRENCES = 60
MAX_DELIVERIES = 120  # messages per request (targets x run times), bounds function time
MAX_DAYS_AHEAD = 119  # Slack accepts post_at up to 120 days ahead
SESSION_SECONDS = 8 * 3600
WORKERS = 5


def _json_env(name: str, default):
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return json.loads(raw)
    except ValueError:
        return default


def bot_token() -> str | None:
    return os.environ.get("SLACK_BOT_TOKEN") or None


def auth_secret() -> str | None:
    return os.environ.get("AUTH_SECRET") or None


def auth_users() -> dict[str, str]:
    """{"tri": "<pbkdf2 hash>", "quyen": "<pbkdf2 hash>"} from tools/hash_password.py."""
    data = _json_env("AUTH_USERS", {})
    return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}


def allowed_channels() -> set[str] | None:
    """Optional allow-list of channel IDs (comma separated). None means any channel the bot can see."""
    raw = os.environ.get("SLACK_ALLOWED_CHANNELS", "")
    ids = {c.strip() for c in raw.split(",") if c.strip()}
    return ids or None


def recipient_lists() -> dict[str, list[str]]:
    """{"leader": ["U123", "U456"]} from env RECIPIENT_LISTS."""
    data = _json_env("RECIPIENT_LISTS", {})
    if not isinstance(data, dict):
        return {}
    return {str(k): [str(u) for u in v] for k, v in data.items() if isinstance(v, list)}


def notify_token() -> str | None:
    """Shared secret for the machine endpoint (header X-Aiops-Token)."""
    return os.environ.get("NOTIFY_TOKEN") or None


def _id_set(name: str) -> set[str]:
    return {c.strip() for c in os.environ.get(name, "").split(",") if c.strip()}


def notify_users() -> set[str]:
    """Slack user IDs the machine endpoint may DM or mention."""
    return _id_set("NOTIFY_ALLOWED_USERS")


def notify_channels() -> set[str]:
    """Channel IDs the machine endpoint may post to."""
    return _id_set("NOTIFY_ALLOWED_CHANNELS")
