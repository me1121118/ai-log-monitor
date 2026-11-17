from __future__ import annotations

import time
from collections import OrderedDict, deque
from collections.abc import Callable
from threading import RLock
from typing import Any


class RollingLogBuffer:
    """Thread-safe, bounded transient context grouped by log source."""

    def __init__(
        self,
        max_age_seconds: float = 300,
        max_entries_per_source: int = 200,
        max_sources: int = 2048,
        max_total_entries: int = 20000,
        clock: Callable[[], float] = time.monotonic,
    ):
        if max_age_seconds <= 0:
            raise ValueError("max_age_seconds must be positive")
        if max_entries_per_source <= 0:
            raise ValueError("max_entries_per_source must be positive")
        if max_sources <= 0 or max_total_entries <= 0:
            raise ValueError("global buffer limits must be positive")
        self._max_age_seconds = float(max_age_seconds)
        self._max_entries_per_source = int(max_entries_per_source)
        self._max_sources = int(max_sources)
        self._max_total_entries = int(max_total_entries)
        self._clock = clock
        self._lock = RLock()
        self._events: OrderedDict[
            tuple[str, str, str], deque[tuple[float, dict[str, Any]]]
        ] = OrderedDict()
        self._total_entries = 0

    def append(self, event: dict[str, Any]) -> None:
        key = self._key(event)
        now = self._clock()
        with self._lock:
            queue = self._events.setdefault(key, deque())
            self._expire(queue, now)
            queue.append((now, self._compact(event)))
            self._total_entries += 1
            while len(queue) > self._max_entries_per_source:
                queue.popleft()
                self._total_entries -= 1
            self._events.move_to_end(key)
            self._enforce_global_limits()

    def context(
        self,
        website_id: str,
        agent_id: str,
        source_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        if limit <= 0:
            return []
        key = (str(website_id), str(agent_id), str(source_id))
        now = self._clock()
        with self._lock:
            queue = self._events.get(key)
            if queue is None:
                return []
            self._expire(queue, now)
            if not queue:
                self._events.pop(key, None)
                return []
            self._events.move_to_end(key)
            return [dict(event) for _, event in list(queue)[-limit:]]

    def context_for(self, event: dict[str, Any], limit: int = 20) -> list[dict[str, Any]]:
        website_id, agent_id, source_id = self._key(event)
        return self.context(website_id, agent_id, source_id, limit=limit)

    def recent_for_source(
        self,
        website_id: str,
        agent_id: str,
        source_id: str,
        file_path: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        now = self._clock()
        matched: list[dict[str, Any]] = []
        target_keys = {str(source_id or ""), str(file_path or "")} - {""}
        with self._lock:
            for (w_id, a_id, s_key), queue in list(self._events.items()):
                if w_id != str(website_id) or a_id != str(agent_id):
                    continue
                self._expire(queue, now)
                if not target_keys or s_key in target_keys:
                    for _, ev in queue:
                        matched.append(dict(ev))
        matched.sort(key=lambda item: str(item.get("timestamp") or ""), reverse=True)
        return matched[:limit]

    def _expire(self, queue: deque[tuple[float, dict[str, Any]]], now: float) -> None:
        cutoff = now - self._max_age_seconds
        while queue and queue[0][0] < cutoff:
            queue.popleft()
            self._total_entries -= 1

    def _enforce_global_limits(self) -> None:
        while len(self._events) > self._max_sources or self._total_entries > self._max_total_entries:
            _key, queue = self._events.popitem(last=False)
            self._total_entries -= len(queue)

    @staticmethod
    def _key(event: dict[str, Any]) -> tuple[str, str, str]:
        website_id = str(event.get("website_id") or "")
        agent_id = str(event.get("agent_id") or "")
        source_id = str(
            event.get("source_id")
            or event.get("file_path")
            or event.get("service")
            or event.get("log_type")
            or "unknown"
        )
        return website_id, agent_id, source_id

    @staticmethod
    def _compact(event: dict[str, Any]) -> dict[str, Any]:
        fields = (
            "website_id",
            "agent_id",
            "agent_role",
            "timestamp",
            "observed_at",
            "severity",
            "category",
            "service",
            "log_type",
            "source_id",
            "file_path",
            "status_code",
            "trace_id",
            "request_id",
        )
        compact = {field: event.get(field) for field in fields if event.get(field) is not None}
        compact["message"] = str(event.get("message") or "")[:4096]
        return compact
