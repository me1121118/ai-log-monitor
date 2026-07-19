from __future__ import annotations

import os
import re
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class LogPath:
    name: str
    path: Path
    type: str
    includes: tuple[str, ...] = ()


@dataclass(frozen=True)
class AgentConfig:
    server_url: str
    enroll_token: str
    agent_id: str
    agent_role: str
    website_id: str
    log_paths: list[LogPath]
    send_only_matched: bool
    keywords: list[str]
    state_dir: Path
    heartbeat_interval_seconds: int


def load_agent_config(path: Path, env: dict[str, str] | None = None) -> AgentConfig:
    env_values = dict(os.environ)
    if env:
        env_values.update(env)
    text = _substitute_env(Path(path).read_text(encoding="utf-8"), env_values)
    raw = _parse_simple_yaml(text)

    log_paths = [
        LogPath(
            name=str(item.get("name") or "log"),
            path=Path(str(item["path"])),
            type=str(item.get("type") or "generic"),
            includes=tuple(str(value).lower() for value in item.get("includes", [])),
        )
        for item in raw.get("logs", {}).get("paths", [])
    ]

    return AgentConfig(
        server_url=str(raw.get("server", {}).get("url") or "").rstrip("/"),
        enroll_token=str(raw.get("enrollment", {}).get("token") or ""),
        agent_id=str(raw.get("agent", {}).get("name") or socket.gethostname() or "agent"),
        agent_role=str(raw.get("agent", {}).get("role") or "unknown"),
        website_id=str(raw.get("agent", {}).get("website_id") or ""),
        log_paths=log_paths,
        send_only_matched=bool(raw.get("filter", {}).get("send_only_matched", True)),
        keywords=[str(value).lower() for value in raw.get("filter", {}).get("keywords", [])],
        state_dir=Path(str(raw.get("runtime", {}).get("state_dir") or "/state")),
        heartbeat_interval_seconds=int(raw.get("runtime", {}).get("heartbeat_interval_seconds") or 30),
    )


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
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        cleaned.append((indent, raw_line.strip()))
    return cleaned


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
        item_text = text[2:].strip()
        index += 1
        if ":" in item_text:
            key, value = _split_key_value(item_text)
            item: dict[str, Any] = {key: _parse_scalar(value or "")}
            while index < len(lines) and lines[index][0] > indent:
                child_indent, child_text = lines[index]
                child_key, child_value = _split_key_value(child_text)
                if child_value is None:
                    raise ValueError(f"nested list item is not supported at: {child_text}")
                item[child_key] = _parse_scalar(child_value)
                index += 1
            result.append(item)
        else:
            result.append(_parse_scalar(item_text))
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
