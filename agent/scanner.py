from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import AgentConfig


BUILT_IN_PROBLEM_TERMS = (
    "error",
    "failed",
    "timeout",
    "timed out",
    "exception",
    "denied",
    "502",
    "503",
    "504",
    "connection refused",
    "too many connections",
    "no space left",
    "disk full",
)


def scan_once(config: AgentConfig) -> list[dict[str, Any]]:
    state = _load_state(config.state_dir)
    events: list[dict[str, Any]] = []

    for log_path in config.log_paths:
        path = log_path.path
        if not path.exists() or not path.is_file():
            continue

        saved_offset = int(state.get(str(path), 0))
        try:
            size = path.stat().st_size
        except OSError:
            continue
        offset = 0 if size < saved_offset else saved_offset

        try:
            with path.open("r", encoding="utf-8", errors="replace") as log_file:
                log_file.seek(offset)
                for raw_line in log_file:
                    message = raw_line.rstrip("\r\n")
                    if not message:
                        continue
                    if _should_send(message, config):
                        events.append(_event_from_line(config, log_path.name, log_path.type, path, message))
                state[str(path)] = log_file.tell()
        except OSError:
            continue

    _save_state(config.state_dir, state)
    return events


def _should_send(message: str, config: AgentConfig) -> bool:
    if not config.send_only_matched:
        return True
    lower = message.lower()
    terms = tuple(config.keywords) + BUILT_IN_PROBLEM_TERMS
    return any(term in lower for term in terms)


def _event_from_line(
    config: AgentConfig,
    log_name: str,
    log_type: str,
    path: Path,
    message: str,
) -> dict[str, Any]:
    return {
        "website_id": config.website_id,
        "agent_id": config.agent_id,
        "agent_role": config.agent_role,
        "log_type": log_name,
        "service": log_type,
        "file_path": str(path),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "message": message,
    }


def _load_state(state_dir: Path) -> dict[str, int]:
    state_path = state_dir / "offsets.json"
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _save_state(state_dir: Path, state: dict[str, int]) -> None:
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "offsets.json").write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
