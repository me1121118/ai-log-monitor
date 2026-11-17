from __future__ import annotations

import re
from typing import Any


_HTTP_REQUEST = re.compile(
    r'"(?P<method>GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+(?P<path>\S+)\s+HTTP/\d(?:\.\d)?"\s+(?P<status>\d{3})',
    re.IGNORECASE,
)
_LATENCY_SECONDS = re.compile(r"(?:request_time|response_time|rt)=(?P<seconds>\d+(?:\.\d+)?)")
_LATENCY_MS = re.compile(r"(?P<milliseconds>\d+(?:\.\d+)?)\s*ms\b", re.IGNORECASE)
_DATABASE_ERROR = re.compile(r"\b(?P<code>MY-\d{6}|SQLSTATE\[[A-Z0-9]+\]|ERROR\s+\d{3,5})\b", re.IGNORECASE)
_SYSLOG_PROGRAM = re.compile(
    r"^(?:\d{4}-\d{2}-\d{2}[T\s]\S+\s+|[A-Z][a-z]{2}\s+\d+\s+\d{2}:\d{2}:\d{2}\s+)?(?:\S+\s+)?(?P<program>[a-zA-Z0-9_.-]+?)(?:\[\d+\])?:\s",
)
_EXPLICIT_LEVEL = re.compile(
    r"(?:\[(?P<b_lvl>TRACE|DEBUG|INFO|NOTICE|WARN|WARNING|ERROR|ERR|CRIT|CRITICAL|FATAL|PANIC)\]"
    r"|\b(?:level|lvl|severity)\s*[:=]\s*[\"']?(?P<kv_lvl>trace|debug|info|notice|warn|warning|error|err|crit|critical|fatal|panic)[\"']?"
    r"|\b(?P<std_lvl>TRACE|DEBUG|INFO|WARN|WARNING|ERROR|FATAL|CRITICAL):)",
    re.IGNORECASE,
)


def _normalize_declared_level(raw: str) -> str:
    val = raw.strip().lower()
    if val in {"trace", "debug"}:
        return "debug"
    if val in {"info", "notice"}:
        return "info"
    if val in {"warn", "warning"}:
        return "warning"
    if val in {"err", "error"}:
        return "error"
    if val in {"crit", "critical", "fatal", "panic"}:
        return "critical"
    return ""


def parse_signal_fields(event: dict[str, Any]) -> dict[str, Any]:
    message = str(event.get("message") or "")[:8192]
    fields: dict[str, Any] = {}

    prog_match = _SYSLOG_PROGRAM.search(message)
    if prog_match:
        prog = prog_match.group("program").lower().strip()
        if prog not in {"http", "https", "get", "post", "put", "delete", "error", "warning", "info", "debug", "fatal", "critical"}:
            fields["writer_program"] = prog

    lvl_match = _EXPLICIT_LEVEL.search(message)
    if lvl_match:
        raw_lvl = lvl_match.group("b_lvl") or lvl_match.group("kv_lvl") or lvl_match.group("std_lvl") or ""
        norm_lvl = _normalize_declared_level(raw_lvl)
        if norm_lvl:
            fields["declared_level"] = norm_lvl

    request = _HTTP_REQUEST.search(message)
    if request:
        fields["request_method"] = request.group("method").upper()
        fields["request_path"] = request.group("path")[:2048]
        fields["status_code"] = int(request.group("status"))

    if event.get("status_code") is not None:
        try:
            fields["status_code"] = int(event["status_code"])
        except (TypeError, ValueError):
            pass

    seconds = _LATENCY_SECONDS.search(message)
    milliseconds = _LATENCY_MS.search(message)
    if seconds:
        fields["latency_ms"] = round(float(seconds.group("seconds")) * 1000, 3)
    elif milliseconds:
        fields["latency_ms"] = float(milliseconds.group("milliseconds"))

    database_error = _DATABASE_ERROR.search(message)
    if database_error:
        fields["database_error_code"] = database_error.group("code").upper().replace("  ", " ")

    return fields
