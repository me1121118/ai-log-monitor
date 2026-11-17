from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .app_common import parse_iso_datetime

class HealthMixin:
    def system_health(self, stale_after_seconds: int = 90) -> dict[str, Any]:
        server_time = datetime.now(timezone.utc)
        checks: dict[str, dict[str, Any]] = {
            "database": self._database_health_check(),
            "data_dir": self._data_dir_health_check(),
            "agents": self._agents_health_check(server_time, stale_after_seconds),
            "incidents": self._incidents_health_check(),
        }
        status = "ok" if all(check.get("status") == "ok" for check in checks.values()) else "degraded"
        return {
            "status": status,
            "server_time": server_time.isoformat(),
            "checks": checks,
        }

    def agents_with_health(self, stale_after_seconds: int = 90) -> list[dict[str, Any]]:
        now = datetime.now(timezone.utc)
        return self._decorate_agents_with_health(self.store.list_agents(), now, stale_after_seconds)

    def _database_health_check(self) -> dict[str, Any]:
        try:
            self.store.list_websites()
            return {"status": "ok", "engine": "sqlite", "path": str(self.store.db_path)}
        except Exception as exc:  # pragma: no cover - defensive for live diagnostics
            return {"status": "degraded", "engine": "sqlite", "error": str(exc)}

    def _data_dir_health_check(self) -> dict[str, Any]:
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            probe_path = self.data_dir / ".healthcheck.tmp"
            probe_path.write_text("ok", encoding="utf-8")
            probe_path.unlink(missing_ok=True)
            return {"status": "ok", "path": str(self.data_dir), "writable": True}
        except Exception as exc:  # pragma: no cover - depends on host filesystem permissions
            return {"status": "degraded", "path": str(self.data_dir), "writable": False, "error": str(exc)}

    def _agents_health_check(self, now: datetime, stale_after_seconds: int) -> dict[str, Any]:
        try:
            agents = self._decorate_agents_with_health(self.store.list_agents(), now, stale_after_seconds)
        except Exception as exc:  # pragma: no cover - database failures are covered by endpoint shape
            return {"status": "degraded", "total": 0, "stale": 0, "offline_agent_ids": [], "error": str(exc)}
        offline_agent_ids: list[str] = []
        agent_details: list[dict[str, Any]] = []
        for agent in agents:
            agent_id = str(agent.get("agent_id") or "")
            if agent.get("health_status") == "stale":
                offline_agent_ids.append(agent_id)
            agent_details.append(
                {
                    "agent_id": agent_id,
                    "website_id": agent.get("website_id"),
                    "last_seen_at": agent.get("last_seen_at"),
                    "status": agent.get("health_status"),
                    "seconds_since_seen": agent.get("seconds_since_seen"),
                }
            )
        return {
            "status": "ok" if not offline_agent_ids else "degraded",
            "total": len(agents),
            "active": len(agents) - len(offline_agent_ids),
            "stale": len(offline_agent_ids),
            "stale_after_seconds": stale_after_seconds,
            "offline_agent_ids": offline_agent_ids,
            "agents": agent_details,
        }

    def _decorate_agents_with_health(
        self,
        agents: list[dict[str, Any]],
        now: datetime,
        stale_after_seconds: int,
    ) -> list[dict[str, Any]]:
        enriched: list[dict[str, Any]] = []
        for agent in agents:
            item = dict(agent)
            last_seen_at = str(item.get("last_seen_at") or "")
            last_seen = parse_iso_datetime(last_seen_at)
            seconds_since_seen = int((now - last_seen).total_seconds()) if last_seen else None
            reported_status = str(item.get("status") or "").lower()
            stale = (
                last_seen is None
                or seconds_since_seen is None
                or seconds_since_seen > stale_after_seconds
                or reported_status in {"offline", "stale", "error"}
            )
            item["health_status"] = "stale" if stale else "active"
            item["seconds_since_seen"] = seconds_since_seen
            item["stale_after_seconds"] = stale_after_seconds
            enriched.append(item)
        return enriched

    def _incidents_health_check(self) -> dict[str, Any]:
        try:
            incidents = self.store.list_incidents()
        except Exception as exc:  # pragma: no cover - database failures are covered by endpoint shape
            return {"status": "degraded", "open": 0, "critical": 0, "error": str(exc)}
        open_incidents = [incident for incident in incidents if incident.get("status") == "open"]
        critical = sum(1 for incident in open_incidents if incident.get("severity") == "critical")
        return {"status": "ok", "open": len(open_incidents), "critical": critical}
