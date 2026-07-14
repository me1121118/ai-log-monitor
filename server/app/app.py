from __future__ import annotations

import json
import re
import secrets
import hmac
import hashlib
from html import escape
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, quote, unquote, urlparse

from .analysis import build_ai_report
from .core import classify_event, normalize_event
from .storage import Store


class AiLogApp:
    def __init__(
        self,
        data_dir: Path,
        enroll_token: str = "change-this-install-token",
        ai_config_path: Path | None = None,
        admin_token: str = "",
        admin_user: str = "",
        admin_password: str = "",
        enforce_agent_token: bool = False,
    ):
        self.data_dir = Path(data_dir)
        self.enroll_token = enroll_token
        self.ai_config_path = ai_config_path or Path(__file__).resolve().parents[1] / "ai.yaml"
        self.admin_token = admin_token.strip()
        self.admin_user = admin_user.strip()
        self.admin_password = admin_password
        self.enforce_agent_token = enforce_agent_token
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
            if method == "POST" and route == "/api/agents/register":
                return self._register(headers, body)
            if method == "GET" and route == "/api/agents":
                return self._json(200, {"agents": self.store.list_agents()})
            if method == "POST" and route == "/api/agents/assign":
                return self._assign_agent(body)
            if method == "GET" and route == "/api/websites":
                return self._json(200, {"websites": self.store.list_websites()})
            if method == "POST" and route == "/api/websites":
                return self._create_website(body)
            if method == "POST" and route == "/api/ingest":
                return self._ingest(headers, body)
            if method == "POST" and route == "/api/files/import":
                return self._import_file(body)
            if method == "GET" and route == "/api/incidents":
                return self._json(200, {"incidents": self.store.list_incidents()})
            if method == "POST" and route.startswith("/api/incidents/") and route.endswith("/close"):
                incident_id = route.removeprefix("/api/incidents/").removesuffix("/close")
                return self._json(200, self.store.close_incident(incident_id))
            if method == "GET" and route == "/api/events/recent":
                return self._json(200, {"events": self.store.recent_events()})
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

    def dashboard_html(self, selected_website_id: str | None = None) -> bytes:
        websites = self.store.list_websites()
        selected = (selected_website_id or "").strip()
        known_ids = {str(website["website_id"]) for website in websites}
        if selected and selected not in known_ids:
            selected = ""
        agents = self.store.list_agents()
        incidents = self.store.list_incidents(selected or None)
        events = self.store.website_context(selected, 20) if selected else self.store.recent_events(20)
        if selected:
            agents = [agent for agent in agents if agent.get("website_id") == selected]
        return _render_dashboard(websites, agents, incidents, events, selected).encode("utf-8")

    def is_admin_authorized(
        self,
        headers: dict[str, str],
        query: dict[str, list[str]] | None = None,
    ) -> bool:
        if not self._admin_enabled():
            return True
        normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
        candidates = [
            normalized_headers.get("x-admin-token", ""),
            (query or {}).get("admin_token", [""])[0],
            _bearer_token(normalized_headers.get("authorization", "")),
            _cookie_value(normalized_headers.get("cookie", ""), "admin_token"),
        ]
        if self.admin_token and any(
            secrets.compare_digest(self.admin_token, str(candidate)) for candidate in candidates if candidate
        ):
            return True
        session = _cookie_value(normalized_headers.get("cookie", ""), "admin_session")
        return self._is_valid_session(session)

    def login_html(self, next_path: str = "/", error: str = "") -> bytes:
        error_html = f'<p class="error">{_h(error)}</p>' if error else ""
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Log Monitor Login</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f6f8; color: #1d2733; }}
    form {{ width: min(420px, calc(100vw - 32px)); background: white; border: 1px solid #d7dde5; border-radius: 6px; padding: 22px; }}
    h1 {{ margin: 0 0 18px; font-size: 22px; }}
    label {{ display: grid; gap: 6px; color: #475467; font-size: 13px; }}
    input, button {{ font: inherit; padding: 10px; border-radius: 4px; border: 1px solid #b8c2cc; }}
    button {{ margin-top: 14px; width: 100%; background: #213547; color: white; cursor: pointer; }}
    .error {{ color: #991b1b; }}
  </style>
</head>
<body>
  <form method="post" action="/login">
    <h1>AI Log Monitor</h1>
    {error_html}
    <input type="hidden" name="next" value="{_h(next_path)}">
    <label>Username<input name="admin_user" type="text" autocomplete="username" required autofocus></label>
    <label>Password<input name="admin_password" type="password" autocomplete="current-password" required></label>
    <button type="submit">Login</button>
  </form>
</body>
</html>""".encode("utf-8")

    def login_response(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        fields = parse_qs(body.decode("utf-8"))
        token = fields.get("admin_token", [""])[0]
        user = fields.get("admin_user", [""])[0]
        password = fields.get("admin_password", [""])[0]
        next_path = fields.get("next", ["/"])[0] or "/"
        if self._is_valid_password_login(user, password):
            session = self._sign_session(user)
            return (
                302,
                {
                    "Location": next_path,
                    "Set-Cookie": f"admin_session={quote(session)}; HttpOnly; SameSite=Lax; Path=/",
                    "Content-Type": "text/plain",
                },
                b"ok",
            )
        if self.admin_token and secrets.compare_digest(self.admin_token, token):
            session_user = self.admin_user or "admin"
            return (
                302,
                {
                    "Location": next_path,
                    "Set-Cookie": f"admin_session={quote(self._sign_session(session_user))}; HttpOnly; SameSite=Lax; Path=/",
                    "Content-Type": "text/plain",
                },
                b"ok",
            )
        return (
            401,
            {"Content-Type": "text/html; charset=utf-8"},
            self.login_html(next_path=next_path, error="Invalid username or password"),
        )

    def _requires_admin(self, method: str, route: str) -> bool:
        if not self._admin_enabled():
            return False
        public_routes = {
            ("GET", "/health"),
            ("POST", "/api/agents/register"),
            ("POST", "/api/ingest"),
        }
        return (method, route) not in public_routes

    def _admin_enabled(self) -> bool:
        return bool(self.admin_token or (self.admin_user and self.admin_password))

    def _session_secret(self) -> str:
        return self.admin_token or self.admin_password

    def _is_valid_password_login(self, user: str, password: str) -> bool:
        if not self.admin_user or not self.admin_password:
            return False
        return secrets.compare_digest(self.admin_user, user) and secrets.compare_digest(self.admin_password, password)

    def _sign_session(self, user: str) -> str:
        signature = hmac.new(
            self._session_secret().encode("utf-8"),
            user.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return f"{user}:{signature}"

    def _is_valid_session(self, session: str) -> bool:
        if not session or ":" not in session or not self._session_secret():
            return False
        user, signature = session.split(":", 1)
        if self.admin_user and not secrets.compare_digest(self.admin_user, user):
            return False
        expected = self._sign_session(user).split(":", 1)[1]
        return secrets.compare_digest(expected, signature)

    def _ingest(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        if self.enforce_agent_token:
            normalized_headers = {str(key).lower(): str(value) for key, value in headers.items()}
            if not self.store.validate_agent_token(
                str(payload.get("agent_id") or ""),
                normalized_headers.get("x-agent-token", ""),
            ):
                return self._json(401, {"error": "invalid agent token"})
        event = classify_event(normalize_event(payload))
        result = self.store.ingest_event(event)
        return self._json(
            201,
            {
                "event_id": result["event_id"],
                "incident_id": result["incident_id"],
                "severity": event["severity"],
                "category": event["category"],
                "fingerprint": event["fingerprint"],
            },
        )

    def _register(self, headers: dict[str, str], body: bytes) -> tuple[int, dict[str, str], bytes]:
        if headers.get("X-Enroll-Token") != self.enroll_token:
            return self._json(401, {"error": "invalid enroll token"})
        payload = json.loads(body.decode("utf-8"))
        payload["registered_at"] = payload.get("registered_at") or datetime.now(timezone.utc).isoformat()
        website_id = str(payload.get("website_id") or "").strip()
        if website_id:
            payload["website_id"] = website_id
            self.store.upsert_website(
                {
                    "website_id": website_id,
                    "name": payload.get("website_name") or website_id,
                    "created_at": payload["registered_at"],
                }
            )
        return self._json(201, self.store.register_agent(payload))

    def _create_website(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        payload["created_at"] = payload.get("created_at") or datetime.now(timezone.utc).isoformat()
        return self._json(201, self.store.upsert_website(payload))

    def _assign_agent(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        return self._json(200, self.store.assign_agent(payload))

    def _import_file(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
        payload = json.loads(body.decode("utf-8"))
        website_id = str(payload.get("website_id") or "").strip()
        content = str(payload.get("content") or "")
        if not website_id:
            raise ValueError("missing website_id")
        if not content:
            raise ValueError("missing content")

        created_at = datetime.now(timezone.utc).isoformat()
        self.store.upsert_website(
            {
                "website_id": website_id,
                "name": payload.get("website_name") or website_id,
                "created_at": created_at,
            }
        )

        filename = _safe_filename(str(payload.get("filename") or "uploaded.log"))
        import_dir = self.data_dir / "imports" / _safe_path_part(website_id)
        import_dir.mkdir(parents=True, exist_ok=True)
        saved_name = f"{_safe_timestamp(created_at)}-{filename}"
        saved_path = import_dir / saved_name
        saved_path.write_text(content, encoding="utf-8")

        agent_id = str(payload.get("agent_id") or "manual_upload").strip() or "manual_upload"
        agent_role = str(payload.get("agent_role") or "manual").strip() or "manual"
        log_type = str(payload.get("log_type") or "uploaded_file").strip() or "uploaded_file"
        service = str(payload.get("service") or log_type).strip() or log_type

        base_time = datetime.now(timezone.utc)
        imported_lines = 0
        problem_lines = 0
        incident_ids: list[str] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            message = line.strip()
            if not message:
                continue
            imported_lines += 1
            event_time = (base_time + timedelta(microseconds=line_number)).isoformat()
            event = classify_event(
                normalize_event(
                    {
                        "website_id": website_id,
                        "agent_id": agent_id,
                        "agent_role": agent_role,
                        "log_type": log_type,
                        "service": service,
                        "file_path": str(saved_path),
                        "timestamp": event_time,
                        "message": message,
                        "metadata": {
                            "filename": filename,
                            "line_number": line_number,
                            "import_mode": "manual_file",
                        },
                    },
                    observed_at=event_time,
                )
            )
            result = self.store.ingest_event(event)
            if event["severity"] in {"problem", "critical"}:
                problem_lines += 1
            if result["incident_id"]:
                incident_ids.append(result["incident_id"])

        return self._json(
            201,
            {
                "website_id": website_id,
                "filename": filename,
                "saved_path": str(saved_path),
                "imported_lines": imported_lines,
                "problem_lines": problem_lines,
                "incident_ids": sorted(set(incident_ids)),
            },
        )

    def _json(self, status: int, payload: dict[str, Any]) -> tuple[int, dict[str, str], bytes]:
        return (
            status,
            {"Content-Type": "application/json"},
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"),
        )


def create_app(
    data_dir: Path,
    enroll_token: str = "change-this-install-token",
    ai_config_path: Path | None = None,
    admin_token: str = "",
    admin_user: str = "",
    admin_password: str = "",
    enforce_agent_token: bool = False,
) -> AiLogApp:
    return AiLogApp(
        data_dir,
        enroll_token=enroll_token,
        ai_config_path=ai_config_path,
        admin_token=admin_token,
        admin_user=admin_user,
        admin_password=admin_password,
        enforce_agent_token=enforce_agent_token,
    )


def _render_dashboard(
    websites: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str = "",
) -> str:
    if not websites and not agents and not incidents and not events:
        return _render_empty_dashboard()

    website_ids = sorted(str(w["website_id"]) for w in websites)
    website_options = "\n".join(f'<option value="{_h(website_id)}"></option>' for website_id in website_ids)
    website_names = {str(website["website_id"]): str(website.get("name") or website["website_id"]) for website in websites}
    agents_by_website: dict[str, int] = {}
    incidents_by_website: dict[str, int] = {}
    for agent in agents:
        website_id = str(agent.get("website_id") or "")
        if website_id:
            agents_by_website[website_id] = agents_by_website.get(website_id, 0) + 1
    for incident in incidents:
        website_id = str(incident.get("website_id") or "")
        if website_id and incident.get("status") == "open":
            incidents_by_website[website_id] = incidents_by_website.get(website_id, 0) + 1
    website_cards = "\n".join(
        f"""
        <a class="website-tile{' active' if website_id == selected_website_id else ''}" data-role="website-tile"
           href="/?website_id={_h(website_id)}" data-website="{_h(website_id)}">
          <span class="tile-id">{_h(website_id)}</span>
          <span class="tile-name">{_h(website_names.get(website_id, website_id))}</span>
          <span class="tile-meta">{agents_by_website.get(website_id, 0)} machine(s) / {incidents_by_website.get(website_id, 0)} open</span>
        </a>""".rstrip()
        for website_id in website_ids
    )
    selected_label = selected_website_id or "all"
    clear_filter_link = '<a class="clear-filter" href="/">All Websites</a>' if selected_website_id else ""
    detail_panel = (
        _render_website_detail(agents, incidents, events, selected_website_id)
        if selected_website_id
        else _render_overview_hint(events)
    )
    website_rows = "\n".join(
        f"<tr><td><a href=\"/?website_id={_h(w['website_id'])}\">{_h(w['website_id'])}</a></td>"
        f"<td>{_h(w['name'])}</td><td>{_h(w['status'])}</td>"
        f"<td>{_h(w['created_at'])}</td></tr>"
        for w in websites
    )
    agent_rows = "\n".join(
        f"<tr><td>{_h(a['agent_id'])}</td><td>{_h(a.get('website_id') or '-')}</td>"
        f"<td>{_h(a['agent_role'])}</td><td>{_h(a['status'])}</td>"
        f"<td>{_h(a.get('hostname') or '-')}</td><td>{_h(a['last_seen_at'])}</td></tr>"
        for a in agents
    )
    incident_rows = "\n".join(
        f"<tr><td>{_h(i['website_id'])}</td><td>{_h(i['severity'])}</td><td>{_h(i['status'])}</td>"
        f"<td>{_h(i['title'])}</td><td>{i['event_count']}</td><td>{_h(i['last_seen_at'])}</td>"
        f"<td><button data-close='{_h(i['incident_id'])}'>Close</button> "
        f"<a href='/api/analyze?website_id={_h(i['website_id'])}'>Analyze</a></td></tr>"
        for i in incidents
    )
    event_rows = "\n".join(
        f"<tr><td>{_h(e['website_id'])}</td><td>{_h(e['agent_id'])}</td><td>{_h(e['severity'])}</td>"
        f"<td>{_h(e['category'])}</td><td>{_h(e['message'])}</td></tr>"
        for e in events
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Log Monitor</title>
  <style>
    * {{ box-sizing: border-box; }}
    body {{ font-family: Arial, sans-serif; margin: 0; color: #1d2733; background: #f3f5f7; }}
    header {{ background: #18212f; color: white; padding: 16px 28px; border-bottom: 1px solid #2e3a4a; }}
    header h1 {{ margin: 0; font-size: 24px; }}
    main {{ padding: 18px 28px 40px; max-width: 1440px; margin: 0 auto; }}
    section {{ margin-bottom: 18px; }}
    h2 {{ margin: 0 0 12px; font-size: 19px; }}
    h3 {{ margin: 0 0 10px; font-size: 15px; }}
    table {{ border-collapse: collapse; width: 100%; margin-bottom: 14px; background: white; border: 1px solid #d6dce4; border-radius: 6px; overflow: hidden; }}
    th, td {{ border-bottom: 1px solid #d7dde5; padding: 9px; text-align: left; vertical-align: top; font-size: 14px; }}
    th {{ background: #eef3f8; color: #344054; }}
    form {{ background: white; border: 1px solid #d7dde5; border-radius: 6px; padding: 14px; margin-bottom: 14px; }}
    label {{ display: grid; gap: 5px; font-size: 13px; color: #475467; }}
    input, button {{ font: inherit; padding: 9px; border: 1px solid #b8c2cc; border-radius: 4px; min-width: 0; }}
    input[type="file"] {{ background: #fbfcfe; }}
    button {{ background: #166534; border-color: #166534; color: white; cursor: pointer; }}
    button.secondary, button[data-close] {{ background: #5b6472; border-color: #5b6472; color: white; }}
    a {{ color: #175cd3; }}
    .top-grid {{ display: grid; grid-template-columns: minmax(280px, 0.78fr) minmax(520px, 1.22fr); gap: 16px; align-items: start; }}
    .website-selector, .overview-hint, .website-detail, .data-shell details {{ background: white; border: 1px solid #d6dce4; border-radius: 6px; padding: 16px; }}
    .website-board {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(112px, 1fr)); gap: 12px; }}
    .website-tile {{ display: grid; gap: 6px; min-height: 92px; padding: 12px; border: 1px solid #c8d2dc; border-radius: 6px; background: #f8fafc; color: #213547; text-decoration: none; }}
    .website-tile.active {{ background: #18212f; border-color: #18212f; color: white; }}
    .tile-id {{ font-weight: 700; overflow-wrap: anywhere; }}
    .tile-name {{ color: inherit; opacity: 0.84; font-size: 13px; overflow-wrap: anywhere; }}
    .tile-meta {{ color: inherit; opacity: 0.72; font-size: 12px; }}
    .clear-filter {{ display: inline-block; margin-left: 8px; font-size: 14px; }}
    .scope-bar {{ display: flex; align-items: center; gap: 10px; flex-wrap: wrap; margin: 0 0 12px; color: #344054; }}
    details {{ background: white; border: 1px solid #d7dde5; border-radius: 6px; padding: 12px 16px; }}
    summary {{ cursor: pointer; font-weight: 700; }}
    .muted {{ color: #667085; }}
    .import-grid {{ display: grid; grid-template-columns: minmax(180px, 1fr) minmax(240px, 2fr) minmax(150px, 1fr) minmax(130px, 1fr) auto; gap: 12px; align-items: end; }}
    .status-line {{ min-height: 22px; color: #344054; font-size: 14px; }}
    .advanced-grid {{ display: grid; grid-template-columns: repeat(4, minmax(140px, 1fr)); gap: 12px; margin-top: 14px; }}
    .website-detail {{ display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 16px; min-height: 360px; }}
    .machine-rail {{ border-right: 1px solid #d6dce4; padding-right: 14px; }}
    .machine-list {{ display: grid; gap: 10px; }}
    .machine-card, .machine-empty {{ background: #f8fafc; border: 1px solid #d7dde5; border-radius: 6px; padding: 12px; min-height: 96px; }}
    .machine-card {{ text-decoration: none; color: inherit; display: grid; gap: 8px; }}
    .machine-card.status-problem, .machine-card.status-critical {{ border-color: #ef9a9a; background: #fff7f7; }}
    .machine-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }}
    .machine-name {{ font-weight: 700; font-size: 17px; overflow-wrap: anywhere; }}
    .machine-role {{ color: #667085; font-size: 13px; margin-top: 2px; }}
    .status-badge {{ display: inline-block; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; white-space: nowrap; }}
    .status-ok {{ background: #dcfce7; color: #166534; }}
    .status-warning {{ background: #fef3c7; color: #92400e; }}
    .status-problem {{ background: #fee2e2; color: #991b1b; }}
    .status-critical {{ background: #7f1d1d; color: white; }}
    .status-nodata {{ background: #eef2f7; color: #475467; }}
    .machine-meta {{ display: grid; gap: 7px; font-size: 13px; color: #344054; }}
    .machine-meta span {{ color: #667085; }}
    .detail-column {{ display: grid; gap: 14px; align-content: start; min-width: 0; }}
    .website-summary, .incident-panel, .log-panel, .import-panel {{ border: 1px solid #d6dce4; border-radius: 6px; padding: 14px; background: #fff; }}
    .detail-head {{ display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; flex-wrap: wrap; }}
    .metric-row {{ display: grid; grid-template-columns: repeat(4, minmax(110px, 1fr)); gap: 10px; margin-top: 12px; }}
    .metric {{ background: #f8fafc; border: 1px solid #e1e6ee; border-radius: 6px; padding: 10px; }}
    .metric strong {{ display: block; font-size: 22px; margin-bottom: 2px; }}
    .metric span {{ color: #667085; font-size: 12px; }}
    .log-panel table {{ margin-bottom: 0; }}
    .data-shell details {{ margin-top: 18px; }}
    @media (max-width: 860px) {{
      header {{ padding: 16px; }}
      main {{ padding: 16px; }}
      .top-grid, .website-detail, .import-grid, .advanced-grid, .metric-row {{ grid-template-columns: 1fr; }}
      .machine-rail {{ border-right: 0; border-bottom: 1px solid #d6dce4; padding-right: 0; padding-bottom: 14px; }}
      th, td {{ font-size: 13px; }}
    }}
  </style>
</head>
<body>
  <header>
    <h1>AI Log Monitor</h1>
  </header>
  <main>
    <div class="top-grid">
      <section class="website-selector">
        <h2>Websites</h2>
        <div class="scope-bar"><strong>Selected Website: {_h(selected_label)}</strong>{clear_filter_link}</div>
        <div class="website-board">{website_cards}</div>
      </section>
      {detail_panel}
    </div>
    <section class="import-panel">
      <h2>Import Log File</h2>
      <form id="file-import">
        <div class="import-grid">
          <label>Website<input name="website_id" list="website-options" value="{_h(selected_website_id or 'website_1')}" required></label>
          <label>Log File<input name="log_file" type="file" required></label>
          <label>Source<input name="agent_id" value="manual_upload" required></label>
          <label>Role<input name="agent_role" value="manual"></label>
          <button type="submit">Import</button>
        </div>
        <input name="log_type" type="hidden" value="uploaded_file">
        <datalist id="website-options">{website_options}</datalist>
      </form>
      <div id="import-status" class="status-line"></div>
    </section>
    <section class="data-shell">
      <details>
        <summary>Advanced Setup</summary>
        <form id="create-website" class="advanced-grid">
          <strong>Create Website</strong>
          <label>Website ID<input name="website_id" placeholder="website_1" required></label>
          <label>Name<input name="name" placeholder="Website 1" required></label>
          <button type="submit" class="secondary">Create</button>
        </form>
        <form id="assign-agent" class="advanced-grid">
          <strong>Assign Agent</strong>
          <label>Agent ID<input name="agent_id" placeholder="web01" required></label>
          <label>Website ID<input name="website_id" placeholder="website_1" required></label>
          <label>Role<input name="agent_role" placeholder="web"></label>
          <button type="submit" class="secondary">Assign</button>
        </form>
      </details>
    </section>
    <section class="data-shell">
      <details>
        <summary>Data Tables</summary>
        <h2>Websites</h2>
        <table>
          <thead><tr><th>Website ID</th><th>Name</th><th>Status</th><th>Created</th></tr></thead>
          <tbody>{website_rows or '<tr><td colspan="4">No websites yet</td></tr>'}</tbody>
        </table>
        <h2>Agents</h2>
        <table>
          <thead><tr><th>Agent</th><th>Website</th><th>Role</th><th>Status</th><th>Hostname</th><th>Last Seen</th></tr></thead>
          <tbody>{agent_rows or '<tr><td colspan="6">No agents yet</td></tr>'}</tbody>
        </table>
        <h2>Incidents</h2>
        <table>
          <thead><tr><th>Website</th><th>Severity</th><th>Status</th><th>Title</th><th>Events</th><th>Last Seen</th><th>Action</th></tr></thead>
          <tbody>{incident_rows or '<tr><td colspan="7">No incidents yet</td></tr>'}</tbody>
        </table>
        <h2>Recent Events</h2>
        <table>
          <thead><tr><th>Website</th><th>Agent</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead>
          <tbody>{event_rows or '<tr><td colspan="5">No events yet</td></tr>'}</tbody>
        </table>
      </details>
    </section>
  </main>
  <script>
    const websiteInput = document.querySelector('#file-import input[name="website_id"]');
    document.querySelectorAll('a[data-website]').forEach((link) => {{
      link.addEventListener('click', () => {{
        websiteInput.value = link.dataset.website;
      }});
    }});

    document.getElementById('file-import').addEventListener('submit', async (event) => {{
      event.preventDefault();
      const form = event.currentTarget;
      const status = document.getElementById('import-status');
      const file = form.log_file.files[0];
      if (!file) {{
        status.textContent = 'Please choose a log file.';
        return;
      }}
      status.textContent = 'Importing...';
      const content = await file.text();
      const data = Object.fromEntries(new FormData(form).entries());
      delete data.log_file;
      data.filename = file.name;
      data.content = content;
      const response = await fetch('/api/files/import', {{
        method: 'POST',
        headers: {{ 'Content-Type': 'application/json' }},
        body: JSON.stringify(data)
      }});
      const result = await response.json();
      if (!response.ok) {{
        status.textContent = result.error || 'Import failed.';
        return;
      }}
      status.textContent = `Imported ${{result.imported_lines}} line(s), problem ${{result.problem_lines}} line(s).`;
      setTimeout(() => location.reload(), 700);
    }});

    async function postJson(url, form) {{
      const data = Object.fromEntries(new FormData(form).entries());
      await fetch(url, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: JSON.stringify(data) }});
      location.reload();
    }}
    document.getElementById('create-website').addEventListener('submit', (event) => {{
      event.preventDefault();
      postJson('/api/websites', event.currentTarget);
    }});
    document.getElementById('assign-agent').addEventListener('submit', (event) => {{
      event.preventDefault();
      postJson('/api/agents/assign', event.currentTarget);
    }});
    document.querySelectorAll('button[data-close]').forEach((button) => {{
      button.addEventListener('click', async () => {{
        await fetch(`/api/incidents/${{button.dataset.close}}/close`, {{ method: 'POST', headers: {{ 'Content-Type': 'application/json' }}, body: '{{}}' }});
        location.reload();
      }});
    }});
  </script>
</body>
</html>"""


def _render_empty_dashboard() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Log Monitor</title>
  <style>
    * { box-sizing: border-box; }
    body { font-family: Arial, sans-serif; margin: 0; min-height: 100vh; color: #1d2733; background: #f3f5f7; }
    header { background: #18212f; color: white; height: 28px; border-bottom: 1px solid #2e3a4a; }
    main { min-height: calc(100vh - 28px); display: grid; place-items: center; padding: 24px; }
    .empty-dashboard { color: #667085; font-size: 14px; }
  </style>
</head>
<body>
  <header></header>
  <main>
    <div class="empty-dashboard">Waiting for agent connection</div>
  </main>
</body>
</html>"""


def _render_overview_hint(events: list[dict[str, Any]]) -> str:
    problem_count = sum(1 for event in events if event["severity"] in {"warning", "problem", "critical"})
    return f"""
      <section class="overview-hint">
        <h2>Pick a website</h2>
        <p class="muted">Use the website boxes on the left to open an isolated monitor view for that website.</p>
        <div class="metric-row">
          <div class="metric"><strong>{len(events)}</strong><span>recent log lines</span></div>
          <div class="metric"><strong>{problem_count}</strong><span>recent problem lines</span></div>
        </div>
      </section>""".rstrip()


def _render_website_detail(
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str,
) -> str:
    open_incidents = [incident for incident in incidents if incident.get("status") == "open"]
    problem_events = [event for event in events if event["severity"] in {"warning", "problem", "critical"}]
    critical_events = [event for event in events if event["severity"] == "critical"]
    latest_event = events[0] if events else None
    latest_label = latest_event["category"] if latest_event else "no_data"
    incident_rows = "\n".join(
        f"<tr><td>{_h(incident['severity'])}</td><td>{_h(incident['status'])}</td>"
        f"<td>{_h(incident['title'])}</td><td>{incident['event_count']}</td>"
        f"<td>{_h(incident['last_seen_at'])}</td>"
        f"<td><button data-close='{_h(incident['incident_id'])}'>Close</button></td></tr>"
        for incident in incidents
    )
    event_rows = "\n".join(
        f"<tr><td>{_h(event['timestamp'])}</td><td>{_h(event['agent_id'])}</td>"
        f"<td><span class=\"status-badge {_severity_badge_class(str(event['severity']))}\">{_h(event['severity'])}</span></td>"
        f"<td>{_h(event['category'])}</td><td>{_h(event['message'])}</td></tr>"
        for event in events
    )
    return f"""
      <section class="website-detail">
        {_render_machine_monitor(agents, events, selected_website_id)}
        <div class="detail-column">
          <section class="website-summary">
            <div class="detail-head">
              <div>
                <h2>{_h(selected_website_id)}</h2>
                <div class="scope-bar"><strong>Selected Website: {_h(selected_website_id)}</strong></div>
              </div>
              <a href="/api/analyze?website_id={_h(selected_website_id)}">Analyze</a>
            </div>
            <div class="metric-row">
              <div class="metric"><strong>{len(agents)}</strong><span>machines</span></div>
              <div class="metric"><strong>{len(open_incidents)}</strong><span>open incidents</span></div>
              <div class="metric"><strong>{len(problem_events)}</strong><span>problem logs</span></div>
              <div class="metric"><strong>{len(critical_events)}</strong><span>critical logs</span></div>
            </div>
            <p class="muted">Latest signal: {_h(latest_label)}</p>
          </section>
          <section class="incident-panel">
            <h2>Incidents</h2>
            <table>
              <thead><tr><th>Severity</th><th>Status</th><th>Title</th><th>Events</th><th>Last Seen</th><th>Action</th></tr></thead>
              <tbody>{incident_rows or '<tr><td colspan="6">No incidents for this website</td></tr>'}</tbody>
            </table>
          </section>
          <section class="log-panel" id="log-panel">
            <h2>Log</h2>
            <table>
              <thead><tr><th>Time</th><th>Machine</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead>
              <tbody>{event_rows or '<tr><td colspan="5">No logs for this website</td></tr>'}</tbody>
            </table>
          </section>
        </div>
      </section>""".rstrip()


def _render_machine_monitor(
    agents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str,
) -> str:
    if not selected_website_id:
        return ""

    latest_by_agent: dict[str, dict[str, Any]] = {}
    problem_counts: dict[str, int] = {}
    for event in events:
        agent_id = str(event["agent_id"])
        latest_by_agent.setdefault(agent_id, event)
        if event["severity"] in {"warning", "problem", "critical"}:
            problem_counts[agent_id] = problem_counts.get(agent_id, 0) + 1

    cards = []
    for agent in sorted(agents, key=lambda item: str(item["agent_id"])):
        agent_id = str(agent["agent_id"])
        latest_event = latest_by_agent.get(agent_id)
        problem_count = problem_counts.get(agent_id, 0)
        status, status_class = _machine_status(latest_event, problem_count)
        last_signal = latest_event["timestamp"] if latest_event else agent["last_seen_at"]
        last_category = latest_event["category"] if latest_event else "no_data"
        hostname = agent.get("hostname") or "-"
        cards.append(
            f"""
          <a class="machine-card {status_class}" href="#log-panel" data-machine="{_h(agent_id)}">
        <div class="machine-head">
          <div>
            <div class="machine-name">{_h(agent_id)}</div>
            <div class="machine-role">{_h(agent['agent_role'])}</div>
          </div>
          <span class="status-badge {status_class}">{_h(status)}</span>
        </div>
        <div class="machine-meta">
          <div><span>Host</span> {_h(hostname)}</div>
          <div><span>Last Signal</span> {_h(last_signal)}</div>
          <div><span>Last Category</span> {_h(last_category)}</div>
          <div><span>Recent Problems</span> {_h(problem_count)}</div>
        </div>
      </a>""".rstrip()
        )

    body = "\n".join(cards) if cards else '<div class="machine-empty">No machines registered in this website.</div>'
    return f"""
        <aside class="machine-rail">
      <h2>Machine Monitor</h2>
      <div class="machine-list">
{body}
      </div>
    </aside>"""


def _severity_badge_class(severity: str) -> str:
    if severity == "critical":
        return "status-critical"
    if severity == "problem":
        return "status-problem"
    if severity == "warning":
        return "status-warning"
    return "status-ok"


def _machine_status(event: dict[str, Any] | None, problem_count: int) -> tuple[str, str]:
    if not event:
        return "No Data", "status-nodata"
    if event["severity"] == "critical":
        return "Critical", "status-critical"
    if problem_count and event["severity"] == "problem":
        return "Problem", "status-problem"
    if problem_count:
        return "Warning", "status-warning"
    return "OK", "status-ok"


def _bearer_token(value: str) -> str:
    prefix = "Bearer "
    return value[len(prefix):].strip() if value.startswith(prefix) else ""


def _cookie_value(cookie_header: str, name: str) -> str:
    for part in cookie_header.split(";"):
        if "=" not in part:
            continue
        key, value = part.split("=", 1)
        if key.strip() == name:
            return unquote(value.strip())
    return ""


def _h(value: Any) -> str:
    return escape(str(value), quote=True)


def _safe_filename(value: str) -> str:
    name = Path(value).name.strip()
    if not name:
        return "uploaded.log"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] or "uploaded.log"


def _safe_path_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())[:80] or "unknown"


def _safe_timestamp(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value)
