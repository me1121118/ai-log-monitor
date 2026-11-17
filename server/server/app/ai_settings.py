from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

DEFAULT_AI_SETTINGS: dict[str, Any] = {
    "ai": {"enabled": True, "mode": "mock", "provider": "none", "model": "none"},
    "analysis": {
        "auto_analyze": True,
        "auto_analyze_min_severity": "critical",
        "max_context_events": 100,
        "time_window_minutes": 30,
    },
    "learning": {"enabled": True, "remember_patterns": True},
    "notifications": {
        "enabled": True,
        "language": "th",
        "line_webhook_url": "",
        "google_chat_webhook_url": "",
    },
    "providers": {
        "ollama": {"url": "http://127.0.0.1:11434/api/generate", "model": "llama3.2:3b"},
        "api": {"endpoint": "", "api_key": "", "model": ""},
    },
    "privacy": {
        "redact_before_send": True,
        "redact_fields": [
            "password",
            "token",
            "secret",
            "authorization",
            "cookie",
            "api_key",
            "connection_string",
        ],
    },
    "limits": {"timeout_seconds": 45, "max_output_tokens": 1200},
}

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


def save_ai_settings(path: Path, incoming: dict[str, Any]) -> dict[str, Any]:
    current = load_ai_settings(path)
    settings = _deep_merge(current, _settings_update_from_payload(incoming))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dump_simple_yaml(settings), encoding="utf-8")
    return load_ai_settings(path, env={})

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


def _settings_update_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    update: dict[str, Any] = {}
    ai = dict(payload.get("ai") or {})
    if ai:
        update["ai"] = {
            "enabled": _coerce_bool(ai.get("enabled"), True),
            "mode": _choice(str(ai.get("mode") or "mock").lower(), {"mock", "ollama", "api"}, "mock"),
            "provider": str(ai.get("provider") or "none").strip() or "none",
            "model": str(ai.get("model") or "none").strip() or "none",
        }

    analysis = dict(payload.get("analysis") or {})
    if analysis:
        update["analysis"] = {
            "auto_analyze": _coerce_bool(analysis.get("auto_analyze"), True),
            "auto_analyze_min_severity": _choice(
                str(analysis.get("auto_analyze_min_severity") or "critical").lower(),
                {"warning", "problem", "critical"},
                "critical",
            ),
            "time_window_minutes": _coerce_int(analysis.get("time_window_minutes"), 30, 1, 1440),
            "max_context_events": _coerce_int(analysis.get("max_context_events"), 100, 1, 2000),
        }

    notifications = dict(payload.get("notifications") or {})
    if notifications:
        update["notifications"] = {
            "enabled": _coerce_bool(notifications.get("enabled"), True),
            "language": _choice(str(notifications.get("language") or "th").lower(), {"th", "en"}, "th"),
            "line_webhook_url": str(notifications.get("line_webhook_url") or "").strip(),
            "google_chat_webhook_url": str(notifications.get("google_chat_webhook_url") or "").strip(),
        }

    providers = dict(payload.get("providers") or {})
    if providers:
        provider_update: dict[str, Any] = {}
        api = dict(providers.get("api") or {})
        if api:
            provider_update["api"] = {
                "endpoint": str(api.get("endpoint") or "").strip(),
                "api_key": str(api.get("api_key") or "").strip(),
                "model": str(api.get("model") or "").strip(),
            }
        ollama = dict(providers.get("ollama") or {})
        if ollama:
            provider_update["ollama"] = {
                "url": str(ollama.get("url") or "http://127.0.0.1:11434/api/generate").strip(),
                "model": str(ollama.get("model") or "llama3.2:3b").strip(),
            }
        if provider_update:
            update["providers"] = provider_update
    return update


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(minimum, min(maximum, number))


def _choice(value: str, allowed: set[str], default: str) -> str:
    return value if value in allowed else default


def _dump_simple_yaml(data: dict[str, Any]) -> str:
    lines: list[str] = [
        "# AI Log Monitor - AI Config",
        "# Managed by the dashboard Settings page. You can still edit this file manually.",
        "",
    ]
    for key in ("ai", "providers", "analysis", "notifications", "learning", "privacy", "limits"):
        if key in data:
            lines.append(f"{key}:")
            _dump_yaml_value(lines, data[key], 2)
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _dump_yaml_value(lines: list[str], value: Any, indent: int) -> None:
    prefix = " " * indent
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, dict):
                lines.append(f"{prefix}{key}:")
                _dump_yaml_value(lines, item, indent + 2)
            elif isinstance(item, list):
                lines.append(f"{prefix}{key}:")
                for entry in item:
                    lines.append(f"{prefix}  - {_format_yaml_scalar(entry)}")
            else:
                lines.append(f"{prefix}{key}: {_format_yaml_scalar(item)}")
        return
    lines.append(f"{prefix}{_format_yaml_scalar(value)}")


def _format_yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    text = str(value)
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


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
