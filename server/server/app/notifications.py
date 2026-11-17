from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .http_client import HttpPost, _http_post_json_allow_empty
from .privacy import redact_text

_ALERT_COOLDOWN_CACHE: dict[str, datetime] = {}


def send_alert_notifications(
    settings: dict[str, Any],
    event: dict[str, Any],
    report: dict[str, Any],
    http_post: HttpPost | None = None,
) -> dict[str, Any]:
    notification_settings = settings.get("notifications", {})
    if not notification_settings.get("enabled", True):
        return {"sent": 0, "channels": [], "errors": []}

    channels = _notification_channels(notification_settings)
    if not channels:
        return {"sent": 0, "channels": [], "errors": []}

    cooldown_seconds = int(notification_settings.get("cooldown_seconds") or 0)
    now_dt = datetime.now(timezone.utc)
    cooldown_key = _cooldown_key(event)
    if cooldown_seconds > 0:
        last_sent = _ALERT_COOLDOWN_CACHE.get(cooldown_key)
        if last_sent and (now_dt - last_sent).total_seconds() < cooldown_seconds:
            return {"sent": 0, "channels": [], "errors": [], "suppressed": True}

    post = http_post or _http_post_json_allow_empty
    timeout = int(settings.get("limits", {}).get("timeout_seconds") or 45)
    text = redact_text(_alert_text(event, report), settings)
    sent_channels: list[str] = []
    errors: list[dict[str, str]] = []
    for channel, url in channels:
        try:
            post(url, {}, {"text": text}, timeout)
            sent_channels.append(channel)
        except Exception as exc:
            errors.append({"channel": channel, "error": str(exc)})

    if sent_channels and cooldown_seconds > 0:
        _ALERT_COOLDOWN_CACHE[cooldown_key] = now_dt

    return {"sent": len(sent_channels), "channels": sent_channels, "errors": errors}


def send_recovery_notification(
    settings: dict[str, Any],
    agent: dict[str, Any],
    cluster_info: dict[str, Any] | None = None,
    http_post: HttpPost | None = None,
) -> list[dict[str, Any]]:
    notification_settings = settings.get("notifications", {})
    if not notification_settings.get("enabled", True):
        return []

    channels = _notification_channels(notification_settings)
    if not channels:
        return []

    agent_id = str(agent.get("agent_id") or "unknown")
    website_id = str(agent.get("website_id") or "unassigned")
    _clear_agent_cooldowns(website_id, agent_id)

    post = http_post or _http_post_json_allow_empty
    timeout = int(settings.get("limits", {}).get("timeout_seconds") or 45)
    text = redact_text(_recovery_text(agent, cluster_info), settings)
    results: list[dict[str, Any]] = []
    for channel, url in channels:
        try:
            post(url, {}, {"text": text}, timeout)
            results.append({"channel": channel, "status": "sent", "text": text})
        except Exception as exc:
            results.append({"channel": channel, "status": "error", "error": str(exc), "text": text})
    return results


def _cooldown_key(event: dict[str, Any]) -> str:
    website_id = str(event.get("website_id") or "")
    agent_id = str(event.get("agent_id") or "")
    category = str(event.get("category") or event.get("fingerprint") or "alert")
    return f"{website_id}|{agent_id}|{category}"


def _clear_agent_cooldowns(website_id: str, agent_id: str) -> None:
    prefix = f"{website_id}|{agent_id}|"
    for key in [k for k in _ALERT_COOLDOWN_CACHE if k.startswith(prefix)]:
        _ALERT_COOLDOWN_CACHE.pop(key, None)


def _notification_channels(notification_settings: dict[str, Any]) -> list[tuple[str, str]]:
    channels: list[tuple[str, str]] = []
    line_url = str(notification_settings.get("line_webhook_url") or "").strip()
    google_chat_url = str(notification_settings.get("google_chat_webhook_url") or "").strip()
    if line_url:
        channels.append(("line", line_url))
    if google_chat_url:
        channels.append(("google_chat", google_chat_url))
    return channels


def _alert_text(event: dict[str, Any], report: dict[str, Any]) -> str:
    evidence = report.get("evidence") or []
    first_evidence = str(evidence[0]) if evidence else str(event.get("message") or "")
    lines = [
        f"Critical log alert: {event.get('website_id')} / {event.get('agent_id')}",
        f"ประเภทปัญหา: {event.get('category')}",
        "สาเหตุที่สงสัย:",
        f"1. {report.get('root_cause')}",
        f"สิ่งที่ควรเช็ค: {report.get('recommended_action')}",
        f"หลักฐานล่าสุด: {first_evidence}",
    ]
    cascading = report.get("cascading_timeline") or []
    if len(cascading) >= 2 and cascading[1].get("cluster_id"):
        lines.append(f"สถานะคลัสเตอร์: {cascading[1].get('title')}")
    return "\n".join(lines)


def _recovery_text(agent: dict[str, Any], cluster_info: dict[str, Any] | None = None) -> str:
    agent_id = str(agent.get("agent_id") or "unknown")
    website_id = str(agent.get("website_id") or "unassigned")
    agent_role = str(agent.get("agent_role") or agent.get("role") or "unknown")
    lines = [
        f"🟢 [Resolved] เครื่อง {agent_id} ({website_id}) กลับมาออนไลน์ปกติแล้ว",
        f"Host Recovered: {agent_id} [role={agent_role}] is back online and healthy.",
    ]
    if cluster_info:
        cluster_id = str(cluster_info.get("cluster_id") or cluster_info.get("id") or agent.get("cluster_id") or "")
        healthy = cluster_info.get("healthy_nodes")
        total = cluster_info.get("total_nodes")
        quorum = cluster_info.get("quorum_status") or (
            "Quorum Maintained" if cluster_info.get("quorum_maintained", True) else "Quorum Restored"
        )
        if cluster_id and healthy is not None and total is not None:
            lines.append(f"สถานะคลัสเตอร์ ({cluster_id}): {healthy}/{total} โหนดออนไลน์ ({quorum})")
        elif cluster_id:
            lines.append(f"สถานะคลัสเตอร์ ({cluster_id}): {quorum}")
    elif agent.get("cluster_id"):
        lines.append(f"คลัสเตอร์: {agent.get('cluster_id')}")
    return "\n".join(lines)
