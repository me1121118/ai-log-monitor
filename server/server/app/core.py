from __future__ import annotations

import hashlib
import posixpath
from datetime import datetime, timezone
from typing import Any

from .log_classifier import classify_event


REQUIRED_EVENT_FIELDS = ("website_id", "agent_id", "timestamp", "message")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_timestamp(value: str, observed_at: str | None = None) -> tuple[str, str]:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).isoformat(), "parsed"
        except ValueError:
            pass
    return observed_at or utc_now_iso(), "fallback_observed_at"


def normalize_event(payload: dict[str, Any], observed_at: str | None = None) -> dict[str, Any]:
    missing = [field for field in REQUIRED_EVENT_FIELDS if not payload.get(field)]
    if missing:
        raise ValueError(f"missing required event field(s): {', '.join(missing)}")

    service = str(payload.get("service") or payload.get("log_type") or "unknown")
    message = str(payload["message"]).strip()
    file_path = payload.get("file_path")
    source_id = str(payload.get("source_id") or "").strip()
    if not source_id and file_path:
        source_id = _source_id_from_path(str(payload["agent_id"]), str(file_path))
    normalized_timestamp, timestamp_confidence = normalize_timestamp(str(payload["timestamp"]), observed_at)
    event_uid = str(payload.get("event_uid") or "").strip()
    source_identity = _clean_source_path(str(file_path)) if file_path else source_id or event_uid
    event_basis = "|".join(
        [
            str(payload["website_id"]),
            str(payload["agent_id"]),
            source_identity,
            normalized_timestamp,
            message,
        ]
    )

    return {
        "event_id": "evt_" + hashlib.sha1(event_basis.encode("utf-8")).hexdigest()[:20],
        "website_id": str(payload["website_id"]),
        "agent_id": str(payload["agent_id"]),
        "agent_role": str(payload.get("agent_role") or payload.get("role") or "unknown"),
        "hostname": payload.get("hostname"),
        "source_ip": payload.get("source_ip"),
        "log_type": str(payload.get("log_type") or "generic"),
        "service": service,
        "file_path": file_path,
        "timestamp": normalized_timestamp,
        "timestamp_confidence": timestamp_confidence,
        "observed_at": observed_at or utc_now_iso(),
        "severity": str(payload.get("severity") or "normal").lower(),
        "status_code": _coerce_status_code(payload.get("status_code")),
        "category": str(payload.get("category") or "unclassified"),
        "message": message,
        "normalized_message": " ".join(message.lower().split()),
        "fingerprint": str(payload.get("fingerprint") or ""),
        "source_id": source_id or None,
        "source_confidence": float(payload.get("source_confidence") or 0.0),
        "event_uid": event_uid or None,
        "multiline": bool(payload.get("multiline", False)),
        "line_count": int(payload.get("line_count") or 1),
        "trace_id": payload.get("trace_id"),
        "request_id": payload.get("request_id"),
        "tags": dict(payload.get("tags") or {}),
        "metadata": dict(payload.get("metadata") or {}),
        "incident_id": payload.get("incident_id"),
    }


def _coerce_status_code(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _source_id_from_path(agent_id: str, file_path: str) -> str:
    basis = f"{agent_id}|{_clean_source_path(file_path)}"
    return "src_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]


def _clean_source_path(file_path: str) -> str:
    return posixpath.normpath(file_path.replace("\\", "/"))
