from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


RAW_ARCHIVE_FIELDS = (
    "event_id",
    "website_id",
    "agent_id",
    "agent_role",
    "log_type",
    "service",
    "source_id",
    "source_confidence",
    "file_path",
    "timestamp",
    "observed_at",
    "severity",
    "category",
    "status_code",
    "fingerprint",
    "message",
    "normalized_message",
    "event_uid",
    "multiline",
    "line_count",
    "metadata",
)


def archive_event(root: Path, event: dict[str, Any]) -> Path:
    path = archive_path_for_event(root, event)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {key: event.get(key) for key in RAW_ARCHIVE_FIELDS if key in event}
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        handle.write("\n")
    return path


def archive_path_for_event(root: Path, event: dict[str, Any]) -> Path:
    website = _safe_part(str(event.get("website_id") or "unknown_website"))
    agent = _safe_part(str(event.get("agent_id") or "unknown_agent"))
    source = _source_folder(event)
    day = _event_day(event)
    return Path(root) / website / agent / source / f"{day}.jsonl"


def _source_folder(event: dict[str, Any]) -> str:
    label = (
        str(event.get("log_type") or "").strip()
        or str(event.get("service") or "").strip()
        or Path(str(event.get("file_path") or "")).name
        or "unknown_source"
    )
    source = _safe_part(label)
    source_id = _safe_part(str(event.get("source_id") or ""))
    if source_id:
        source = f"{source}--{source_id[:14]}"
    return source[:120] or "unknown_source"


def _event_day(event: dict[str, Any]) -> str:
    for key in ("timestamp", "observed_at"):
        value = str(event.get(key) or "").strip()
        if not value:
            continue
        parsed = _parse_iso(value)
        if parsed:
            return parsed.date().isoformat()
    return datetime.now(timezone.utc).date().isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _safe_part(value: str) -> str:
    part = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())
    part = part.replace("..", "_")
    part = re.sub(r"_+", "_", part).strip("._-")
    return part[:80]
