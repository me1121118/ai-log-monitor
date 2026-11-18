from __future__ import annotations

from typing import Any

from .log_parsers import parse_signal_fields
from .log_profiles import profile_source


def classify_event(event: dict[str, Any]) -> dict[str, Any]:
    classified = dict(event)
    profile = profile_source(classified)
    parsed_fields = parse_signal_fields(classified)
    if classified.get("status_code") is None and parsed_fields.get("status_code") is not None:
        classified["status_code"] = parsed_fields["status_code"]
    message = str(classified.get("normalized_message") or "")
    status_code = classified.get("status_code")
    service = str(classified.get("service") or "unknown").lower().replace("-", "_")

    severity = "normal"
    category = "normal"

    writer_prog = str(parsed_fields.get("writer_program") or "").lower()
    declared_lvl = str(parsed_fields.get("declared_level") or "").lower()
    raw_msg = str(classified.get("message") or "")

    is_sudo_cmd = (
        writer_prog == "sudo"
        or ("sudo:" in message and ("tty=" in message or "command=" in message or "pwd=" in message))
    )
    is_sshd_noise = (
        writer_prog in {"sshd", "sshd-session"}
        or "sshd[" in message
        or "sshd-session[" in message
    ) and _contains_any(
        message,
        (
            "connection reset by peer",
            "kex_exchange_identification",
            "read error from remote host",
            "disconnected from",
            "received disconnect",
            "connection closed by",
        ),
    )
    is_kernel_display_noise = (
        writer_prog == "kernel" or "kernel:" in message
    ) and _contains_any(message, ("vblank wait timed out", "[crtc:", "[drm]"))

    disk_readonly_terms = (
        "read-only file system",
        "remounting filesystem read-only",
        "remount-ro",
        "aborting journal",
    )
    disk_io_terms = (
        "i/o error",
        "buffer i/o error",
        "blk_update_request",
        "ext4-fs error",
        "xfs error",
        "end_request: i/o error",
    )
    disk_slow_terms = (
        "blocked for more than",
        "hung_task_timeout_secs",
        "page_cleaner",
        "long semaphore wait",
    )
    critical_resource_terms = (
        "out of memory",
        "oom",
        "disk full",
        "no space left",
    ) + disk_readonly_terms + disk_io_terms

    if is_sudo_cmd:
        severity = "normal"
        category = "admin_command"
    elif is_sshd_noise:
        severity = "normal"
        category = "ssh_disconnect"
    elif is_kernel_display_noise:
        severity = "normal"
        category = "kernel_display"
    elif declared_lvl in {"debug", "info"} and not (
        isinstance(status_code, int) and status_code >= 400
    ) and not _contains_any(message, critical_resource_terms):
        severity = "normal"
        category = "normal"
    elif "agent_spool_loss_marker" in message:
        severity = "problem"
        category = "agent_data_loss"
    elif _contains_any(message, disk_readonly_terms):
        severity = "critical"
        category = "disk_readonly"
    elif _contains_any(message, disk_io_terms):
        severity = "critical"
        category = "disk_io_error"
    elif _contains_any(message, ("out of memory", "oom", "disk full", "no space left")):
        severity = "critical"
        category = "disk_full" if _contains_any(message, ("disk full", "no space left")) else "out_of_memory"
    elif _contains_any(message, disk_slow_terms):
        severity = "problem"
        category = "disk_slow_io"
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
    elif _contains_any(message, ("warning", "retry", "slow query")) or declared_lvl == "warning":
        severity = "warning"
        category = "warning"
    elif declared_lvl == "critical":
        severity = "critical"
        category = "critical"
    elif declared_lvl == "error":
        severity = "problem"
        category = "error"

    explicit = str(event.get("severity") or "").lower()
    if (
        explicit in {"warning", "problem", "critical"}
        and severity == "normal"
        and category not in {"admin_command", "ssh_disconnect", "kernel_display"}
    ):
        severity = explicit
        category = category if category != "normal" else explicit

    signal_type, category, classification = enrich_classification(
        classified, severity, category, profile=profile
    )
    classified["signal_type"] = signal_type
    classified["severity"] = severity
    classified["category"] = category
    classified["metadata"] = dict(classified.get("metadata") or {})
    classified["metadata"]["classification"] = classification
    classified["metadata"]["source_profile"] = profile
    if parsed_fields:
        classified["metadata"]["parsed_fields"] = parsed_fields
    classified["fingerprint"] = classified.get("fingerprint") or f"fp_{service}_{category}"
    return classified


def enrich_classification(
    event: dict[str, Any],
    severity: str,
    category: str,
    profile: dict[str, Any] | None = None,
) -> tuple[str, str, dict[str, Any]]:
    """Add an explainable signal type and rule record to a classified event."""
    service = str(event.get("service") or "").lower().replace("-", "_")
    log_type = str(event.get("log_type") or "").lower().replace("-", "_")
    file_path = str(event.get("file_path") or "").lower().replace("\\", "/")
    message = str(event.get("normalized_message") or "")
    status_code = event.get("status_code")

    active_profile = profile or profile_source(event)
    signal_type = str(active_profile["service_class"])
    if active_profile["traffic_candidate"] and isinstance(status_code, int):
        signal_type = "traffic"
    basis: list[str] = []
    if service:
        basis.append("service_name")
    if log_type or file_path:
        basis.append("source_path")
    if category != "normal":
        basis.append("message_keyword")
    if isinstance(status_code, int):
        basis.append("status_code")

    if severity == "normal" and signal_type == "traffic":
        category = "traffic_request"
        rule_id = "traffic.http_success.v1" if isinstance(status_code, int) else "traffic.access.v1"
        confidence = 0.98
    elif category == "db_too_many_connections":
        rule_id = "db.connection_limit.v1"
        confidence = 0.98
    elif severity == "critical" and category in {"out_of_memory", "disk_full", "disk_readonly", "disk_io_error"}:
        rule_id = "system.resource_critical.v1"
        confidence = 0.99
    elif category == "disk_slow_io":
        rule_id = "system.disk_slow_io.v1"
        confidence = 0.92
    elif category == "upstream_timeout":
        rule_id = "proxy.upstream_timeout.v1"
        confidence = 0.96
    elif category == "http_5xx":
        rule_id = "traffic.http_error.v1" if signal_type == "traffic" else "application.http_error.v1"
        confidence = 0.94
    elif severity == "warning":
        rule_id = "signal.warning.v1"
        confidence = 0.82
    elif severity in {"problem", "critical"}:
        rule_id = "signal.problem.v1"
        confidence = 0.78
    elif signal_type == "unknown":
        rule_id = "source.unknown_normal.v1"
        confidence = 0.5
        basis = ["fallback"]
    else:
        rule_id = "signal.normal.v1"
        confidence = 0.75

    return signal_type, category, {
        "rule_id": rule_id,
        "confidence": confidence,
        "basis": basis,
    }


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
