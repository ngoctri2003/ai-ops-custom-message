"""Parse and validate a send request, and turn it into a plan. No Slack calls here."""
import re
from datetime import date, datetime, timedelta

from . import config
from .schedule import RULE_LABELS, occurrences, once_at, parse_hhmm, next_occurrence

CHANNEL_RE = re.compile(r"^[CG][A-Z0-9]{8,}$")
SUBTEAM_RE = re.compile(r"^S[A-Z0-9]{8,}$")
TIME_RE = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def build_text(text: str, mention: str, usergroups: list[str]) -> str:
    parts = []
    if mention == "channel":
        parts.append("<!channel>")
    elif mention == "here":
        parts.append("<!here>")
    parts.extend(f"<!subteam^{g}>" for g in usergroups)
    prefix = " ".join(parts)
    return f"{prefix}\n{text}" if prefix else text


def recipients_of(lists: list[str], recipient_lists: dict[str, list[str]]) -> list[str]:
    seen, out = set(), []
    for name in lists:
        for uid in recipient_lists.get(name, []):
            if uid not in seen:
                seen.add(uid)
                out.append(uid)
    return out


def normalize(body: dict) -> dict:
    def as_list(key):
        value = body.get(key) or []
        return [str(x) for x in value] if isinstance(value, list) else []

    def as_str(key, default=""):
        value = body.get(key)
        return str(value).strip() if value not in (None, "") else default

    return {
        "text": as_str("text"),
        "channels": as_list("channels"),
        "usergroups": as_list("usergroups"),
        "lists": as_list("lists"),
        "mention": as_str("mention", "none"),
        "when": as_str("when", "now"),
        "date": as_str("date") or None,
        "time": as_str("time") or None,
        "rule": as_str("rule", "once"),
        "until": as_str("until") or None,
        "dry_run": bool(body.get("dry_run")),
    }


def _parse_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value) if value else None
    except ValueError:
        return None


def compute_runs(s: dict, now: datetime) -> tuple[list[datetime], dict[str, str]]:
    """Run times for a scheduled request, plus field errors."""
    errors: dict[str, str] = {}
    if not s["time"] or not TIME_RE.match(s["time"]):
        return [], {"time": "Chọn giờ gửi (giờ Việt Nam)."}
    if s["rule"] not in RULE_LABELS:
        return [], {"rule": "Quy tắc lặp không hợp lệ."}
    tod = parse_hhmm(s["time"])
    limit = now + timedelta(days=config.MAX_DAYS_AHEAD)

    if s["rule"] == "once":
        d = _parse_date(s["date"])
        if not d:
            return [], {"date": "Chọn ngày gửi."}
        run = once_at(d, tod, config.TZ)
        if run <= now:
            return [], {"date": "Thời điểm này đã qua."}
        if run > limit:
            return [], {"date": f"Chỉ đặt lịch được trong {config.MAX_DAYS_AHEAD} ngày tới."}
        return [run], errors

    until = _parse_date(s["until"])
    if not until:
        return [], {"until": "Chọn ngày kết thúc lặp."}
    if until > limit.date():
        return [], {"until": f"Tối đa đến {limit.date():%d/%m/%Y} (giới hạn {config.MAX_DAYS_AHEAD} ngày của Slack)."}
    first = next_occurrence(s["rule"], now, tod, config.TZ)
    if first.date() > until:
        return [], {"until": "Ngày kết thúc sớm hơn lần chạy đầu tiên."}
    runs = occurrences(s["rule"], first, until, tod, config.TZ, config.MAX_OCCURRENCES)
    if len(runs) > config.MAX_OCCURRENCES:
        return [], {"until": f"Tối đa {config.MAX_OCCURRENCES} lần lặp, hãy chọn ngày kết thúc sớm hơn."}
    return runs, errors


def validate(s: dict, now: datetime, recipient_lists: dict[str, list[str]],
             allowed_channels: set[str] | None) -> tuple[dict[str, str], list[datetime]]:
    errors: dict[str, str] = {}
    if not s["text"]:
        errors["text"] = "Nội dung không được để trống."
    elif len(s["text"]) > config.MAX_TEXT:
        errors["text"] = f"Nội dung tối đa {config.MAX_TEXT} ký tự."
    if s["mention"] not in ("none", "channel", "here"):
        errors["mention"] = "Giá trị không hợp lệ."
    if s["when"] not in ("now", "schedule"):
        errors["when"] = "Giá trị không hợp lệ."

    if len(s["channels"]) > config.MAX_CHANNELS:
        errors["channels"] = f"Tối đa {config.MAX_CHANNELS} channel mỗi lần."
    elif any(not CHANNEL_RE.match(c) for c in s["channels"]):
        errors["channels"] = "Channel không hợp lệ."
    elif allowed_channels is not None and any(c not in allowed_channels for c in s["channels"]):
        errors["channels"] = "Có channel nằm ngoài danh sách được phép."
    if any(not SUBTEAM_RE.match(g) for g in s["usergroups"]):
        errors["usergroups"] = "User group không hợp lệ."
    unknown = [n for n in s["lists"] if n not in recipient_lists]
    recipients = recipients_of(s["lists"], recipient_lists)
    if unknown:
        errors["lists"] = "Danh sách người nhận không tồn tại."
    elif len(recipients) > config.MAX_RECIPIENTS:
        errors["lists"] = f"Tối đa {config.MAX_RECIPIENTS} người nhận mỗi lần."

    if "channels" not in errors:
        if not s["channels"] and not s["lists"]:
            errors["channels"] = "Chọn ít nhất một channel hoặc một danh sách người nhận."
        elif s["usergroups"] and not s["channels"]:
            errors["usergroups"] = "User group được mention trong channel, hãy chọn thêm channel."
    if s["mention"] in ("channel", "here") and not s["channels"]:
        errors["mention"] = "@channel/@here chỉ áp dụng khi gửi vào channel."

    runs: list[datetime] = []
    if s["when"] == "schedule":
        runs, run_errors = compute_runs(s, now)
        errors.update(run_errors)
    if not errors:
        targets = len(s["channels"]) + len(recipients)
        total = targets * max(len(runs), 1)
        if total > config.MAX_DELIVERIES:
            errors["channels"] = (f"Quá nhiều tin ({total}, tối đa {config.MAX_DELIVERIES}). "
                                  "Giảm số đích hoặc số lần lặp.")
    return errors, runs
