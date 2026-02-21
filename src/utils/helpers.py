"""Helper utilities."""

from datetime import datetime, timedelta


def human_duration(seconds: int) -> str:
    if seconds < 60:
        return f"{seconds}s"
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def time_ago(dt: datetime) -> str:
    diff = datetime.now() - dt
    s = int(diff.total_seconds())
    if s < 60:
        return "just now"
    if s < 3600:
        return f"{s // 60} min ago"
    if s < 86400:
        return f"{s // 3600}h ago"
    if s < 172800:
        return "yesterday"
    return dt.strftime("%b %d")


def truncate(text: str, max_len: int = 40) -> str:
    return text if len(text) <= max_len else text[:max_len - 1] + "…"