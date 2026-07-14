from __future__ import annotations

import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import request

from .storage import Store


DEFAULT_AI_SETTINGS: dict[str, Any] = {
    "ai": {"enabled": True, "mode": "mock", "provider": "none", "model": "none"},
    "analysis": {"max_context_events": 100},
    "learning": {"enabled": True, "remember_patterns": True},
    "providers": {
        "ollama": {"url": "http://127.0.0.1:11434/api/generate", "model": "llama3.2:3b"},
        "api": {"endpoint": "", "api_key": "", "model": ""},
    },
    "limits": {"timeout_seconds": 45, "max_output_tokens": 1200},
}


HttpPost = Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]]


def load_ai_settings(path: Path | None = None, env: dict[str, str] | None = None) -> dict[str, Any]:
    settings = _deep_copy(DEFAULT_AI_SETTINGS)
    if not path or not Path(path).exists():
        return settings
    env_values = dict(os.environ)
    if env:
        env_values.update(env)
    text = _substitute_env(Path(path).read_text(encoding="utf-8"), env_values)
    loaded = _parse_simple_yaml(text)
    return _deep_merge(settings, loaded)


def build_mock_ai_report(store: Store, website_id: str, limit: int = 100) -> dict[str, Any]:
    settings = _deep_copy(DEFAULT_AI_SETTINGS)
    settings["analysis"]["max_context_events"] = limit
    return build_ai_report(store, website_id, settings=settings)


def build_ai_report(
    store: Store,
    website_id: str,
    settings: dict[str, Any] | None = None,
    config_path: Path | None = None,
    http_post: HttpPost | None = None,
) -> dict[str, Any]:
    active_settings = settings or load_ai_settings(config_path)
    limit = int(active_settings.get("analysis", {}).get("max_context_events") or 100)
    events = store.website_context(website_id, limit=limit)
    problem_events = [event for event in events if event["severity"] in {"warning", "problem", "critical"}]
    fingerprints = sorted({event["fingerprint"] for event in problem_events})
    memory_matches = store.match_incident_memory(website_id, fingerprints)
    report = _build_rule_report(website_id, problem_events, memory_matches)

    mode = str(active_settings.get("ai", {}).get("mode") or "mock").lower()
    enabled = bool(active_settings.get("ai", {}).get("enabled", True))
    if enabled and mode in {"ollama", "api"} and problem_events:
        prompt = _build_prompt(website_id, problem_events, memory_matches)
        llm_text = _call_configured_ai(active_settings, prompt, http_post=http_post)
        if llm_text:
            report["mode"] = mode
            report["summary"] = llm_text
            report["provider"] = active_settings.get("ai", {}).get("provider") or mode
            report["confidence"] = max(float(report["confidence"]), 0.72)
        else:
            report["provider"] = "fallback_mock"
    else:
        report["provider"] = "none"

    _remember_pattern(store, report, problem_events, active_settings, bool(memory_matches))
    return report


def _build_rule_report(
    website_id: str,
    problem_events: list[dict[str, Any]],
    memory_matches: list[dict[str, Any]],
) -> dict[str, Any]:
    agents = sorted({event["agent_id"] for event in problem_events})
    categories = Counter(event["category"] for event in problem_events)
    fingerprints = sorted({event["fingerprint"] for event in problem_events})
    evidence = [
        f"{event['timestamp']} {event['agent_id']} {event['category']} {event['message']}"
        for event in problem_events[:20]
    ]

    if not problem_events:
        return {
            "website_id": website_id,
            "mode": "mock",
            "agents_checked": [],
            "summary": f"No problem evidence found for {website_id}.",
            "root_cause": "No problem evidence found.",
            "recommended_action": "No action required from current evidence.",
            "confidence": 0.0,
            "evidence": [],
            "fingerprints": [],
            "memory_status": "none",
            "memory_matches": [],
        }

    root_cause, recommended_action, confidence = _infer_root_cause(problem_events, categories)
    top_category, count = categories.most_common(1)[0]
    summary = (
        f"{website_id}: found {len(problem_events)} non-normal event(s). "
        f"Top signal is {top_category} x{count}. "
        f"Checked agents: {', '.join(agents)}. "
        f"Root cause: {root_cause}"
    )
    if memory_matches:
        summary += f" Known pattern matched: {memory_matches[0]['root_cause']}"

    return {
        "website_id": website_id,
        "mode": "mock",
        "agents_checked": agents,
        "summary": summary,
        "root_cause": root_cause,
        "recommended_action": recommended_action,
        "confidence": confidence,
        "evidence": evidence,
        "fingerprints": fingerprints,
        "memory_status": "matched" if memory_matches else "new",
        "memory_matches": memory_matches,
    }


def _infer_root_cause(
    problem_events: list[dict[str, Any]],
    categories: Counter,
) -> tuple[str, str, float]:
    db_events = [event for event in problem_events if event["category"] == "db_too_many_connections"]
    timeout_events = [
        event
        for event in problem_events
        if event["category"] in {"upstream_timeout", "timeout", "connection_refused"}
    ]
    critical_events = [event for event in problem_events if event["severity"] == "critical"]

    if db_events and timeout_events:
        db_agents = ", ".join(sorted({event["agent_id"] for event in db_events}))
        web_agents = ", ".join(sorted({event["agent_id"] for event in timeout_events}))
        return (
            f"{db_agents} reported too many connections, then {web_agents} reported upstream timeout.",
            "Check database connection limits, slow queries, and app connection pool settings before restarting web workers.",
            0.84,
        )
    if db_events:
        db_agents = ", ".join(sorted({event["agent_id"] for event in db_events}))
        return (
            f"{db_agents} reported too many connections.",
            "Check DB max connections, connection leaks, slow queries, and pool sizing.",
            0.76,
        )
    if critical_events:
        agents = ", ".join(sorted({event["agent_id"] for event in critical_events}))
        top_category = Counter(event["category"] for event in critical_events).most_common(1)[0][0]
        return (
            f"{agents} reported critical {top_category}.",
            "Check host resources first, then restart only the affected service if resources are stable.",
            0.8,
        )
    top_category, _count = categories.most_common(1)[0]
    agents = ", ".join(sorted({event["agent_id"] for event in problem_events if event["category"] == top_category}))
    return (
        f"{agents} reported repeated {top_category}.",
        "Review the affected service logs around the same timestamp and compare with upstream/downstream agents in this website.",
        0.65,
    )


def _remember_pattern(
    store: Store,
    report: dict[str, Any],
    problem_events: list[dict[str, Any]],
    settings: dict[str, Any],
    had_memory_match: bool,
) -> None:
    learning = settings.get("learning", {})
    if not learning.get("enabled", True) or not learning.get("remember_patterns", True):
        report["memory_status"] = "disabled"
        return
    if not problem_events:
        return

    categories = Counter(event["category"] for event in problem_events)
    top_category, _count = categories.most_common(1)[0]
    primary = next(event for event in problem_events if event["category"] == top_category)
    observed_at = str(primary.get("timestamp") or datetime.now(timezone.utc).isoformat())
    memory = store.upsert_incident_memory(
        {
            "website_id": report["website_id"],
            "fingerprint": primary["fingerprint"],
            "category": top_category,
            "root_cause": report["root_cause"],
            "suggested_action": report["recommended_action"],
            "observed_at": observed_at,
            "confidence": report["confidence"],
        }
    )
    if had_memory_match:
        report["memory_status"] = "matched"
        return
    report["memory_status"] = "stored"
    report["memory_matches"] = [memory]


def _build_prompt(
    website_id: str,
    problem_events: list[dict[str, Any]],
    memory_matches: list[dict[str, Any]],
) -> str:
    event_lines = "\n".join(
        f"- {event['timestamp']} {event['agent_id']} {event['agent_role']} {event['category']}: {event['message']}"
        for event in problem_events[:40]
    )
    memory_lines = "\n".join(
        f"- {item['category']}: {item['root_cause']} | action: {item['suggested_action']}"
        for item in memory_matches[:5]
    )
    return (
        "You are an on-prem log incident analyst. Analyze only the supplied website scope.\n"
        f"Website: {website_id}\n"
        "Return a short Thai report with root cause, affected machines, and next checks.\n"
        "Events:\n"
        f"{event_lines}\n"
        "Known matching patterns:\n"
        f"{memory_lines or '- none'}"
    )


def _call_configured_ai(
    settings: dict[str, Any],
    prompt: str,
    http_post: HttpPost | None = None,
) -> str:
    mode = str(settings.get("ai", {}).get("mode") or "mock").lower()
    timeout = int(settings.get("limits", {}).get("timeout_seconds") or 45)
    post = http_post or _http_post_json
    try:
        if mode == "ollama":
            provider = settings.get("providers", {}).get("ollama", {})
            url = str(provider.get("url") or "http://127.0.0.1:11434/api/generate")
            model = str(settings.get("ai", {}).get("model") or provider.get("model") or "llama3.2:3b")
            response = post(url, {}, {"model": model, "prompt": prompt, "stream": False}, timeout)
            return str(response.get("response") or "").strip()
        if mode == "api":
            provider = settings.get("providers", {}).get("api", {})
            endpoint = str(provider.get("endpoint") or "").strip()
            api_key = str(provider.get("api_key") or "").strip()
            model = str(settings.get("ai", {}).get("model") or provider.get("model") or "").strip()
            if not endpoint or not api_key or not model:
                return ""
            response = post(
                endpoint,
                {"Authorization": f"Bearer {api_key}"},
                {"model": model, "messages": [{"role": "user", "content": prompt}]},
                timeout,
            )
            return str(response.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception:
        return ""
    return ""


def _http_post_json(url: str, headers: dict[str, str], payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    request_body = json.dumps(payload).encode("utf-8")
    req = request.Request(
        url,
        data=request_body,
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    with request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _substitute_env(text: str, env: dict[str, str]) -> str:
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda match: env.get(match.group(1), ""), text)


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines = _clean_lines(text)
    if not lines:
        return {}
    value, index = _parse_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError("could not parse full config")
    if not isinstance(value, dict):
        raise ValueError("top-level config must be a mapping")
    return value


def _clean_lines(text: str) -> list[tuple[int, str]]:
    cleaned: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        line = _strip_comment(raw_line.rstrip())
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        cleaned.append((indent, line.strip()))
    return cleaned


def _strip_comment(line: str) -> str:
    in_quote = ""
    for index, char in enumerate(line):
        if char in {"'", '"'}:
            in_quote = "" if in_quote == char else char
        if char == "#" and not in_quote:
            return line[:index].rstrip()
    return line


def _parse_block(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[Any, int]:
    if lines[index][1].startswith("- "):
        return _parse_list(lines, index, indent)
    return _parse_map(lines, index, indent)


def _parse_map(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line_indent, text = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"unexpected indentation at: {text}")
        if text.startswith("- "):
            break
        key, value = _split_key_value(text)
        index += 1
        if value is None:
            if index < len(lines) and lines[index][0] > line_indent:
                result[key], index = _parse_block(lines, index, lines[index][0])
            else:
                result[key] = {}
        else:
            result[key] = _parse_scalar(value)
    return result, index


def _parse_list(lines: list[tuple[int, str]], index: int, indent: int) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line_indent, text = lines[index]
        if line_indent < indent or not text.startswith("- "):
            break
        if line_indent != indent:
            raise ValueError(f"unexpected list indentation at: {text}")
        result.append(_parse_scalar(text[2:].strip()))
        index += 1
    return result, index


def _split_key_value(text: str) -> tuple[str, str | None]:
    if ":" not in text:
        raise ValueError(f"expected key/value line: {text}")
    key, value = text.split(":", 1)
    value = value.strip()
    return key.strip(), value if value else None


def _parse_scalar(value: str) -> Any:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        return int(value)
    except ValueError:
        return value


def _deep_merge(base: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    result = _deep_copy(base)
    for key, value in incoming.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))
