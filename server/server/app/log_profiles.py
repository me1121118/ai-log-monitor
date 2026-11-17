from __future__ import annotations

from typing import Any


def profile_source(event: dict[str, Any]) -> dict[str, Any]:
    service = str(event.get("service") or "").lower().replace("-", "_")
    log_type = str(event.get("log_type") or "").lower().replace("-", "_")
    file_path = str(event.get("file_path") or "").lower().replace("\\", "/")
    source = " ".join((service, log_type, file_path))

    service_class = _service_class(source)
    source_kind = _source_kind(source, service_class)
    traffic_candidate = source_kind == "access" or (
        "haproxy" in source and source_kind == "journal"
    )
    return {
        "service_class": service_class,
        "source_kind": source_kind,
        "traffic_candidate": traffic_candidate,
    }


def _service_class(source: str) -> str:
    if _contains_any(source, ("mysql", "mariadb", "postgres", "postgresql", "redis", "database")):
        return "database"
    if _contains_any(source, ("haproxy", "nginx", "apache", "httpd", "proxy")):
        return "proxy"
    if _contains_any(source, ("auth", "audit", "security", "login")):
        return "security"
    if _contains_any(source, ("kernel", "syslog", "journalctl", "system", "dmesg")):
        return "system"
    if _contains_any(source, ("app", "application", "django", "node", "gunicorn", "uvicorn")):
        return "application"
    return "unknown"


def _source_kind(source: str, service_class: str) -> str:
    if "access" in source:
        return "access"
    if "error" in source:
        return "error"
    if "journal" in source:
        return "journal"
    if service_class == "system":
        return "system"
    if "audit" in source or "auth" in source:
        return "audit"
    return "generic"


def _contains_any(text: str, needles: tuple[str, ...]) -> bool:
    return any(needle in text for needle in needles)
