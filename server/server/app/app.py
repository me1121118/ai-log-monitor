from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from .analysis import HttpPost, build_ai_report, load_ai_settings, save_ai_settings
from .app_auth import AuthMixin
from .app_handlers import RequestHandlersMixin
from .app_health import HealthMixin
from .storage import Store
from .rolling_buffer import RollingLogBuffer
from .traffic_anomaly import TrafficAnomalyDetector
from .ui import DASHBOARD_PAGES, _render_dashboard
from .utils import LOG_PAGE_SIZE, _positive_int

class AiLogApp(HealthMixin, AuthMixin, RequestHandlersMixin):
    def __init__(
        self,
        data_dir: Path,
        enroll_token: str = "change-this-install-token",
        ai_config_path: Path | None = None,
        admin_token: str = "",
        admin_user: str = "",
        admin_password: str = "",
        enforce_agent_token: bool = False,
        public_url: str = "http://10.1.0.10:8888",
        notification_post: HttpPost | None = None,
        gateway_internal_token: str = "",
    ):
        self.data_dir = Path(data_dir)
        self.enroll_token = enroll_token
        self.gateway_internal_token = gateway_internal_token.strip()
        self.ai_config_path = ai_config_path or Path(__file__).resolve().parents[1] / "ai.yaml"
        self.admin_token = admin_token.strip()
        self.admin_user = admin_user.strip()
        self.admin_password = admin_password
        self.enforce_agent_token = enforce_agent_token
        self.public_url = (public_url or "http://10.1.0.10:8888").rstrip("/")
        self.notification_post = notification_post
        self.rolling_logs = RollingLogBuffer(max_age_seconds=86400)
        self.traffic_detector = TrafficAnomalyDetector()
        self.store = Store(self.data_dir / "database.db")
        self.store.init()

    def handle_json(
        self,
        method: str,
        path: str,
        headers: dict[str, str],
        body: bytes,
    ) -> tuple[int, dict[str, str], bytes]:
        try:
            parsed = urlparse(path)
            route = parsed.path
            query = parse_qs(parsed.query)
            if self._requires_admin(method, route) and not self.is_admin_authorized(headers, query):
                return self._json(401, {"error": "admin authentication required"})
            if method == "GET" and route == "/health":
                return self._json(200, {"status": "ok"})
            if method == "GET" and route == "/api/system/health":
                return self._json(200, self.system_health())
            if method == "POST" and route == "/api/agents/register":
                return self._register(headers, body)
            if method == "POST" and route == "/api/agents/heartbeat":
                return self._heartbeat(headers, body)
            if method == "GET" and route == "/api/agents":
                return self._json(200, {"agents": self.agents_with_health()})
            if method == "POST" and route == "/api/agents/assign":
                return self._assign_agent(body)
            if method == "POST" and route == "/api/agents/delete":
                payload = json.loads(body.decode("utf-8") or "{}")
                agent_id = str(payload.get("agent_id") or "").strip()
                return self._json(200, {"deleted": self.store.delete_agent(agent_id), "agent_id": agent_id})
            if method == "DELETE" and route.startswith("/api/agents/"):
                agent_id = route.removeprefix("/api/agents/").strip("/")
                return self._json(200, {"deleted": self.store.delete_agent(agent_id), "agent_id": agent_id})
            if method == "POST" and route == "/api/agents/maintenance":
                return self._set_agent_maintenance(body)
            if method == "GET" and route == "/api/clusters":
                website_id = (query.get("website_id") or [""])[0] or None
                return self._json(200, {"clusters": self.store.list_clusters(website_id)})
            if method == "POST" and route == "/api/clusters":
                return self._upsert_cluster(body)
            if method == "POST" and route == "/api/clusters/delete":
                payload = json.loads(body.decode("utf-8") or "{}")
                cluster_id = str(payload.get("cluster_id") or "").strip()
                return self._json(200, {"deleted": self.store.delete_cluster(cluster_id), "cluster_id": cluster_id})
            if method == "DELETE" and route.startswith("/api/clusters/"):
                cluster_id = route.removeprefix("/api/clusters/").strip("/")
                return self._json(200, {"deleted": self.store.delete_cluster(cluster_id), "cluster_id": cluster_id})
            if method == "GET" and route == "/api/relations":
                website_id = (query.get("website_id") or [""])[0] or None
                return self._json(200, {"relations": self.store.list_vm_relations(website_id)})
            if method == "POST" and route == "/api/relations":
                return self._upsert_relation(body)
            if method == "DELETE" and route.startswith("/api/relations/"):
                relation_id = route.removeprefix("/api/relations/").strip("/")
                return self._json(200, {"deleted": self.store.delete_vm_relation(relation_id), "relation_id": relation_id})
            if method == "GET" and route == "/api/topology-graph":
                website_id = (query.get("website_id") or [""])[0] or "website_1"
                return self._json(200, self.store.build_er_topology_graph(website_id))
            if method == "GET" and route == "/api/traffic":
                website_id = (query.get("website_id") or [""])[0] or "website_1"
                return self._json(200, self.traffic_detector.get_website_traffic_summary(website_id))
            if method == "GET" and route == "/api/storage/daily":
                return self._json(200, {"files": self.store.list_daily_db_files()})
            if method == "GET" and route == "/api/websites":
                return self._json(200, {"websites": self.store.list_websites()})
            if method == "POST" and route == "/api/websites":
                return self._create_website(body)
            if method == "POST" and route == "/api/websites/delete":
                payload = json.loads(body.decode("utf-8") or "{}")
                wid = str(payload.get("website_id") or "").strip()
                return self._json(200, {"deleted": self.store.delete_website(wid), "website_id": wid})
            if method == "DELETE" and route.startswith("/api/websites/"):
                wid = route.removeprefix("/api/websites/").strip("/")
                return self._json(200, {"deleted": self.store.delete_website(wid), "website_id": wid})
            if method == "POST" and route == "/api/log-sources":
                return self._upsert_log_sources(headers, body)
            if method == "GET" and route == "/api/log-sources":
                website_id = (query.get("website_id") or [""])[0] or None
                agent_id = (query.get("agent_id") or [""])[0] or None
                return self._json(200, {"sources": self.store.list_log_sources(website_id, agent_id)})
            if method == "POST" and route == "/api/topology-hints":
                return self._upsert_topology_hints(headers, body)
            if method == "GET" and route == "/api/topology-hints":
                website_id = (query.get("website_id") or [""])[0] or None
                agent_id = (query.get("agent_id") or [""])[0] or None
                return self._json(200, {"hints": self.store.list_topology_hints(website_id, agent_id)})
            if method == "POST" and route == "/api/ingest":
                return self._ingest(headers, body)
            if method == "POST" and route == "/api/ingest/batch":
                return self._ingest_batch(headers, body)
            if method == "POST" and route == "/internal/evidence":
                return self._internal_evidence(headers, body)
            if method == "POST" and route == "/internal/agents/validate":
                return self._internal_agent_validate(headers, body)
            if method == "POST" and route == "/api/files/import":
                return self._import_file(body)
            if method == "GET" and route == "/api/incidents":
                return self._json(200, {"incidents": self.store.list_incidents()})
            if method == "POST" and route.startswith("/api/incidents/") and route.endswith("/close"):
                incident_id = route.removeprefix("/api/incidents/").removesuffix("/close")
                return self._json(200, self.store.close_incident(incident_id))
            if method == "POST" and route == "/api/incidents/suppress":
                payload = json.loads(body.decode("utf-8") or "{}")
                return self._json(
                    200,
                    self.store.suppress_incident(
                        incident_id=str(payload.get("incident_id") or "").strip(),
                        website_id=str(payload.get("website_id") or "").strip(),
                        title=str(payload.get("title") or "").strip(),
                    ),
                )
            if method == "POST" and route.startswith("/api/incidents/") and route.endswith("/suppress"):
                incident_id = route.removeprefix("/api/incidents/").removesuffix("/suppress")
                return self._json(200, self.store.suppress_incident(incident_id=incident_id))
            if method == "GET" and route == "/api/events/recent":
                return self._json(200, {"events": self.store.recent_events()})
            if method == "GET" and route == "/api/settings":
                return self._json(200, {"settings": load_ai_settings(self.ai_config_path)})
            if method == "POST" and route == "/api/settings":
                return self._json(200, {"settings": save_ai_settings(self.ai_config_path, json.loads(body.decode("utf-8")))})
            if method == "GET" and route == "/api/analyze":
                website_id = (query.get("website_id") or [""])[0]
                if not website_id:
                    return self._json(400, {"error": "missing website_id"})
                return self._json(200, build_ai_report(self.store, website_id, config_path=self.ai_config_path))
            return self._json(404, {"error": "not_found"})
        except ValueError as exc:
            return self._json(400, {"error": str(exc)})
        except json.JSONDecodeError:
            return self._json(400, {"error": "invalid JSON body"})

    def dashboard_html(
        self,
        selected_website_id: str | None = None,
        selected_agent_id: str | None = None,
        selected_source_id: str | None = None,
        log_page: int = 1,
        page: str = "overview",
    ) -> bytes:
        websites = self.store.list_websites()
        selected_page = page if page in DASHBOARD_PAGES else "overview"
        selected = (selected_website_id or "").strip()
        selected_agent = (selected_agent_id or "").strip()
        selected_source = (selected_source_id or "").strip()
        known_ids = {str(website["website_id"]) for website in websites}
        if selected and selected not in known_ids:
            selected = ""
        if selected_page == "website" and not selected and websites:
            selected = str(websites[0]["website_id"])
        agents = self.agents_with_health()
        incidents = self.store.list_incidents(selected or None)
        page = _positive_int(log_page, default=1)
        scoped_agent = selected_agent if selected_page == "website" else None
        scoped_source = selected_source if selected_page == "website" else None
        total_log_events = self.store.count_events(selected or None, scoped_agent, scoped_source)
        max_log_page = max(1, (total_log_events + LOG_PAGE_SIZE - 1) // LOG_PAGE_SIZE)
        page = min(page, max_log_page)
        log_events = self.store.event_page(
            selected or None,
            limit=LOG_PAGE_SIZE,
            offset=(page - 1) * LOG_PAGE_SIZE,
            agent_id=scoped_agent,
            source_id=scoped_source,
        )
        events = self.store.website_context(selected, 100) if selected else self.store.recent_events(20)
        log_sources = self.store.list_log_sources(selected or None) if selected else []
        raw_source_logs: list[dict[str, Any]] = []
        if selected and selected_agent and selected_source:
            src_obj = next(
                (s for s in log_sources if str(s.get("agent_id") or "") == selected_agent and str(s.get("source_id") or "") == selected_source),
                None,
            )
            fpath = str(src_obj.get("path") or "") if src_obj else ""
            raw_source_logs = self.rolling_logs.recent_for_source(selected, selected_agent, selected_source, file_path=fpath, limit=50)
        topology_hints = self.store.list_topology_hints(selected or None) if selected else []
        er_topology = self.store.build_er_topology_graph(selected) if selected else None
        traffic_summary = self.traffic_detector.get_website_traffic_summary(selected) if selected else None
        if selected:
            agents = [agent for agent in agents if agent.get("website_id") == selected]
        settings = dict(load_ai_settings(self.ai_config_path))
        if selected_page == "settings":
            settings["system_health"] = self.system_health()
        return _render_dashboard(
            websites,
            agents,
            incidents,
            events,
            selected,
            log_events=log_events,
            log_page=page,
            total_log_events=total_log_events,
            log_sources=log_sources,
            topology_hints=topology_hints,
            settings=settings,
            page=selected_page,
            public_url=self.public_url,
            selected_agent_id=selected_agent,
            selected_source_id=selected_source,
            er_topology=er_topology,
            traffic_summary=traffic_summary,
            raw_source_logs=raw_source_logs,
        ).encode("utf-8")

def create_app(
    data_dir: Path,
    enroll_token: str = "change-this-install-token",
    ai_config_path: Path | None = None,
    admin_token: str = "",
    admin_user: str = "",
    admin_password: str = "",
    enforce_agent_token: bool = False,
    public_url: str = "http://10.1.0.10:8888",
    notification_post: HttpPost | None = None,
    gateway_internal_token: str = "",
) -> AiLogApp:
    return AiLogApp(
        data_dir,
        enroll_token=enroll_token,
        ai_config_path=ai_config_path,
        admin_token=admin_token,
        admin_user=admin_user,
        admin_password=admin_password,
        enforce_agent_token=enforce_agent_token,
        public_url=public_url,
        notification_post=notification_post,
        gateway_internal_token=gateway_internal_token,
    )
