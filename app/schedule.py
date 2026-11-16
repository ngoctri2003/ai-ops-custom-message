"""Schedule rules. All wall-clock logic uses Asia/Ho_Chi_Minh."""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

RULE_LABELS = {
    "once": "Không lặp (một lần)",
    "daily": "Hằng ngày",
    "weekdays": "Thứ 2 đến thứ 6",
    "weekly:0": "Hằng tuần, thứ 2",
    "weekly:1": "Hằng tuần, thứ 3",
    "weekly:2": "Hằng tuần, thứ 4",
    "weekly:3": "Hằng tuần, thứ 5",
    "weekly:4": "Hằng tuần, thứ 6",
    "weekly:5": "Hằng tuần, thứ 7",
    "weekly:6": "Hằng tuần, chủ nhật",
}


def _matches(rule: str, d: date) -> bool:
    if rule in ("once", "daily"):
        return True
    if rule == "weekdays":
        return d.weekday() < 5
    if rule.startswith("weekly:"):
        return d.weekday() == int(rule.split(":", 1)[1])
    raise ValueError(f"unknown rule: {rule}")


def parse_hhmm(value: str) -> time:
    hh, mm = value.split(":")
    return time(int(hh), int(mm))


def once_at(d: date, tod: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(d, tod, tzinfo=tz)


def next_occurrence(rule: str, after: datetime, tod: time, tz: ZoneInfo) -> datetime:
    """First run strictly after `after` that matches the rule."""
    after = after.astimezone(tz)
    for i in range(0, 9):
        d = after.date() + timedelta(days=i)
        candidate = datetime.combine(d, tod, tzinfo=tz)
        if candidate > after and _matches(rule, d):
            return candidate
    raise ValueError("no occurrence found")


def occurrences(rule: str, first: datetime, until: date, tod: time, tz: ZoneInfo, cap: int) -> list[datetime]:
    """Run times from `first` through the end of day `until`, at most cap + 1 (so callers can detect overflow)."""
    out = [first]
    cur = first
    while len(out) <= cap:
        cur = next_occurrence(rule, cur, tod, tz)
        if cur.date() > until:
            break
        out.append(cur)
    return out
