from __future__ import annotations

import json
from typing import Any, Callable
from urllib import request

HttpPost = Callable[[str, dict[str, str], dict[str, Any], int], dict[str, Any]]

def _http_post_json_allow_empty(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: int,
) -> dict[str, Any]:
    request_body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url,
        data=request_body,
        method="POST",
        headers={"Content-Type": "application/json", **headers},
    )
    with request.urlopen(req, timeout=timeout) as response:
        raw = response.read().decode("utf-8").strip()
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"response": raw}


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
