from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any


REQUIRED_EVENT_FIELDS = ("website_id", "agent_id", "timestamp", "message")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_event(payload: dict[str, Any], observed_at: str | None = None) -> dict[str, Any]:
    missing = [field for field in REQUIRED_EVENT_FIELDS if not payload.get(field)]
    if missing:
        raise ValueError(f"missing required event field(s): {', '.join(missing)}")

    service = str(payload.get("service") or payload.get("log_type") or "unknown")
    message = str(payload["message"]).strip()
    event_basis = "|".join(
        [
            str(payload["website_id"]),
            str(payload["agent_id"]),
            str(payload["timestamp"]),
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
        "file_path": payload.get("file_path"),
        "timestamp": str(payload["timestamp"]),
        "observed_at": observed_at or utc_now_iso(),
        "severity": str(payload.get("severity") or "normal").lower(),
        "status_code": _coerce_status_code(payload.get("status_code")),
        "category": str(payload.get("category") or "unclassified"),
        "message": message,
        "normalized_message": " ".join(message.lower().split()),
        "fingerprint": str(payload.get("fingerprint") or ""),
        "trace_id": payload.get("trace_id"),
        "request_id": payload.get("request_id"),
        "tags": dict(payload.get("tags") or {}),
        "metadata": dict(payload.get("metadata") or {}),
        "incident_id": payload.get("incident_id"),
    }


def classify_event(event: dict[str, Any]) -> dict[str, Any]:
    classified = dict(event)
    message = classified["normalized_message"]
    status_code = classified.get("status_code")
    service = str(classified.get("service") or "unknown").lower().replace("-", "_")

    severity = "normal"
    category = "normal"

    if _contains_any(message, ("out of memory", "oom", "disk full", "no space left")):
        severity = "critical"
        category = "disk_full" if _contains_any(message, ("disk full", "no space left")) else "out_of_memory"
    elif _contains_any(message, ("upstream timed out", "timeout", "timed out")):
        severity = "problem"
        category = "upstream_timeout" if "upstream" in message else "timeout"
    elif _contains_any(message, ("connection refused", "cannot connect", "connection reset")):
        severity = "problem"
        category = "connection_refused"
    elif "too many connections" in message:
        severity = "problem"
        category = "db_too_many_connections"
    elif _contains_any(message, ("permission denied", "access denied")):
        severity = "problem"
        category = "permission_denied"
    elif isinstance(status_code, int) and status_code >= 500:
        severity = "problem"
        category = "http_5xx"
    elif isinstance(status_code, int) and status_code >= 400:
        severity = "warning"
        category = "http_4xx"
    elif _contains_any(message, ("warning", "retry", "slow query")):
        severity = "warning"
        category = "warning"

    explicit = str(event.get("severity") or "").lower()
    if explicit in {"warning", "problem", "critical"} and severity == "normal":
        severity = explicit
        category = category if category != "normal" else explicit

    classified["severity"] = severity
    classified["category"] = category
    classified["fingerprint"] = classified.get("fingerprint") or f"fp_{service}_{category}"
    return classified


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)


def _coerce_status_code(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
