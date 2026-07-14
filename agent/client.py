from __future__ import annotations

import json
from typing import Any
from urllib import request


class AgentClient:
    def __init__(self, server_url: str, timeout_seconds: int = 10):
        self.server_url = server_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def register(self, enroll_token: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            "/api/agents/register",
            payload,
            headers={"X-Enroll-Token": enroll_token},
        )

    def ingest(self, agent_token: str, event: dict[str, Any]) -> dict[str, Any]:
        return self._post(
            "/api/ingest",
            event,
            headers={"X-Agent-Token": agent_token},
        )

    def _post(self, path: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        body = json.dumps(payload).encode("utf-8")
        req = request.Request(
            self.server_url + path,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                **headers,
            },
        )
        with request.urlopen(req, timeout=self.timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
