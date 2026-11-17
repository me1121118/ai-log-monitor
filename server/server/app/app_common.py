from datetime import datetime, timezone

def severity_at_least(severity: str, minimum: str) -> bool:
    order = {"normal": 0, "warning": 1, "problem": 2, "critical": 3}
    return order.get(severity.lower(), 0) >= order.get(minimum.lower(), 3)


def parse_iso_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)
