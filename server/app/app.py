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
        error_html = f'<div class="error">{_h(error)}</div>' if error else ""
        return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Log Monitor - Login</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #070a13;
      --card-bg: rgba(15, 23, 42, 0.75);
      --border: rgba(255, 255, 255, 0.08);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #6366f1;
      --primary-glow: rgba(99, 102, 241, 0.4);
    }}
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', sans-serif;
      background: radial-gradient(circle at center, #0f172a 0%, var(--bg) 100%);
      color: var(--text);
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 20px;
    }}
    .container {{
      width: 100%;
      max-width: 440px;
      position: relative;
    }}
    .container::before {{
      content: '';
      position: absolute;
      width: 150px;
      height: 150px;
      background: var(--primary);
      filter: blur(100px);
      top: -50px;
      right: -50px;
      z-index: -1;
      opacity: 0.5;
    }}
    .container::after {{
      content: '';
      position: absolute;
      width: 150px;
      height: 150px;
      background: #06b6d4;
      filter: blur(100px);
      bottom: -50px;
      left: -50px;
      z-index: -1;
      opacity: 0.3;
    }}
    form {{
      background: var(--card-bg);
      backdrop-filter: blur(20px);
      border: 1px solid var(--border);
      border-radius: 16px;
      padding: 40px 32px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.4);
    }}
    h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: 28px;
      font-weight: 700;
      margin-bottom: 8px;
      text-align: center;
      background: linear-gradient(135deg, #fff 30%, var(--text-muted) 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .subtitle {{
      color: var(--text-muted);
      font-size: 14px;
      text-align: center;
      margin-bottom: 28px;
    }}
    .error {{
      background: rgba(239, 68, 68, 0.15);
      border: 1px solid rgba(239, 68, 68, 0.3);
      color: #fca5a5;
      padding: 12px;
      border-radius: 8px;
      font-size: 13px;
      margin-bottom: 20px;
      text-align: center;
    }}
    .input-group {{
      margin-bottom: 20px;
      display: grid;
      gap: 8px;
    }}
    label {{
      color: var(--text-muted);
      font-size: 13px;
      font-weight: 500;
    }}
    input {{
      font-family: inherit;
      background: rgba(7, 10, 19, 0.6);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px 16px;
      color: var(--text);
      font-size: 15px;
      transition: all 0.25s ease;
      outline: none;
    }}
    input:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 0 3px var(--primary-glow);
    }}
    button {{
      font-family: inherit;
      font-weight: 600;
      margin-top: 10px;
      width: 100%;
      background: linear-gradient(135deg, var(--primary) 0%, #4f46e5 100%);
      color: white;
      border: none;
      padding: 14px;
      border-radius: 8px;
      font-size: 15px;
      cursor: pointer;
      transition: all 0.25s ease;
      box-shadow: 0 4px 12px var(--primary-glow);
    }}
    button:hover {{
      transform: translateY(-2px);
      box-shadow: 0 6px 20px rgba(99, 102, 241, 0.6);
    }}
    button:active {{
      transform: translateY(0);
    }}
  </style>
</head>
<body>
  <div class="container">
    <form method="post" action="/login">
      <h1>AI Log Monitor</h1>
      <p class="subtitle">Secure Operational Portal</p>
      {error_html}
      <input type="hidden" name="next" value="{_h(next_path)}">
      <div class="input-group">
        <label for="admin_user">Username</label>
        <input id="admin_user" name="admin_user" type="text" autocomplete="username" required autofocus>
      </div>
      <div class="input-group">
        <label for="admin_password">Password</label>
        <input id="admin_password" name="admin_password" type="password" autocomplete="current-password" required>
      </div>
      <button type="submit">Access Console</button>
    </form>
  </div>
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
          <span class="tile-meta">{agents_by_website.get(website_id, 0)} host(s) / {incidents_by_website.get(website_id, 0)} open</span>
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
        f"<tr><td><a href='/?website_id={_h(w['website_id'])}' style='color: var(--cyan); font-weight: 600;'>{_h(w['website_id'])}</a></td>"
        f"<td>{_h(w['name'])}</td><td><span class='status-badge status-ok'>{_h(w['status'])}</span></td>"
        f"<td>{_h(w['created_at'])}</td></tr>"
        for w in websites
    )
    agent_rows = "\n".join(
        f"<tr><td><strong style='color:#fff;'>{_h(a['agent_id'])}</strong></td><td>{_h(a.get('website_id') or '-')}</td>"
        f"<td><span style='font-family: monospace; opacity: 0.85;'>{_h(a['agent_role'])}</span></td>"
        f"<td><span class='status-badge {_severity_badge_class('ok' if a['status']=='online' else 'critical')}'>{_h(a['status'])}</span></td>"
        f"<td>{_h(a.get('hostname') or '-')}</td><td class='log-time'>{_h(a['last_seen_at'])}</td></tr>"
        for a in agents
    )
    incident_rows = "\n".join(
        f"<tr><td>{_h(i['website_id'])}</td><td><span class='status-badge {_severity_badge_class(str(i['severity']))}'>{_h(i['severity'])}</span></td>"
        f"<td><span class='status-badge {_severity_badge_class('warning' if i['status']=='open' else 'ok')}'>{_h(i['status'])}</span></td>"
        f"<td><strong style='color:#fff;'>{_h(i['title'])}</strong></td><td>{i['event_count']}</td><td class='log-time'>{_h(i['last_seen_at'])}</td>"
        f"<td><button class='close-btn-sm' data-close='{_h(i['incident_id'])}'>Close</button> "
        f"<button class='ai-btn-sm' onclick=\"runAiAnalysis('{_h(i['website_id'])}')\">✨ Analyze</button></td></tr>"
        for i in incidents
    )
    event_rows = "\n".join(
        f"<tr><td>{_h(e['website_id'])}</td><td>{_h(e['agent_id'])}</td>"
        f"<td><span class='status-badge {_severity_badge_class(str(e['severity']))}'>{_h(e['severity'])}</span></td>"
        f"<td class='log-cat'>{_h(e['category'])}</td><td class='log-message'>{_h(e['message'])}</td></tr>"
        for e in events
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Log Monitor</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
  <style>
    :root {{
      --bg: #07090e;
      --card-bg: rgba(17, 24, 39, 0.6);
      --card-hover: rgba(31, 41, 55, 0.8);
      --border: rgba(255, 255, 255, 0.06);
      --border-hover: rgba(255, 255, 255, 0.12);
      --text: #f3f4f6;
      --text-muted: #9ca3af;
      --primary: #6366f1;
      --primary-glow: rgba(99, 102, 241, 0.25);
      --cyan: #06b6d4;
      --cyan-glow: rgba(6, 182, 212, 0.25);
      --ok: #10b981;
      --warning: #f59e0b;
      --problem: #ef4444;
      --critical: #ec4899;
      --nodata: #64748b;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      font-family: 'Inter', sans-serif;
      margin: 0;
      color: var(--text);
      background-color: var(--bg);
      background-image: 
        radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.12) 0px, transparent 50%),
        radial-gradient(at 100% 100%, rgba(6, 182, 212, 0.08) 0px, transparent 50%);
      min-height: 100vh;
      display: flex;
      flex-direction: column;
    }}
    header {{
      background: rgba(15, 23, 42, 0.6);
      backdrop-filter: blur(12px);
      border-bottom: 1px solid var(--border);
      padding: 16px 28px;
      position: sticky;
      top: 0;
      z-index: 100;
    }}
    .header-container {{
      max-width: 1440px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .logo {{
      display: flex;
      align-items: center;
      gap: 12px;
    }}
    .logo h1 {{
      font-family: 'Outfit', sans-serif;
      font-size: 22px;
      font-weight: 700;
      margin: 0;
      letter-spacing: 0.5px;
      background: linear-gradient(135deg, #fff 0%, #a5b4fc 100%);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }}
    .pulse-dot {{
      width: 10px;
      height: 10px;
      background: var(--ok);
      border-radius: 50%;
      box-shadow: 0 0 10px var(--ok);
      animation: simple-pulse 2s infinite;
    }}
    @keyframes simple-pulse {{
      0% {{ box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }}
      70% {{ box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }}
      100% {{ box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }}
    }}
    .status-indicator {{
      font-family: monospace;
      font-size: 11px;
      color: var(--ok);
      border: 1px solid rgba(16, 185, 129, 0.3);
      padding: 4px 8px;
      border-radius: 4px;
      background: rgba(16, 185, 129, 0.05);
      letter-spacing: 1px;
    }}
    .ops-shell {{
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      min-height: 100vh;
    }}
    .sidebar {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 22px 14px;
      background: linear-gradient(180deg, rgba(15, 23, 42, 0.92), rgba(15, 23, 42, 0.72));
      border-right: 1px solid var(--border);
      display: flex;
      flex-direction: column;
      gap: 22px;
    }}
    .brand-mark {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 0 8px 12px;
      border-bottom: 1px solid var(--border);
      font-family: 'Outfit', sans-serif;
      font-size: 18px;
      font-weight: 700;
      color: #fff;
    }}
    .brand-icon {{
      width: 34px;
      height: 34px;
      border-radius: 9px;
      display: grid;
      place-items: center;
      background: rgba(6, 182, 212, 0.16);
      color: var(--cyan);
      border: 1px solid rgba(6, 182, 212, 0.24);
    }}
    .nav-list {{
      display: grid;
      gap: 6px;
    }}
    .nav-item {{
      display: flex;
      align-items: center;
      gap: 10px;
      padding: 10px 12px;
      border-radius: 8px;
      color: var(--text-muted);
      text-decoration: none;
      font-size: 14px;
      border: 1px solid transparent;
    }}
    .nav-item.active, .nav-item:hover {{
      color: var(--cyan);
      background: rgba(6, 182, 212, 0.1);
      border-color: rgba(6, 182, 212, 0.14);
    }}
    .sidebar-footer {{
      margin-top: auto;
      padding: 12px;
      border-top: 1px solid var(--border);
      color: var(--text-muted);
      font-size: 12px;
      line-height: 1.5;
    }}
    .workspace {{
      min-width: 0;
      display: flex;
      flex-direction: column;
    }}
    main {{
      padding: 24px 28px 40px;
      max-width: 1440px;
      width: 100%;
      margin: 0 auto;
      flex-grow: 1;
      display: flex;
      flex-direction: column;
      gap: 20px;
    }}
    section {{
      margin-bottom: 0;
    }}
    h2 {{
      font-family: 'Outfit', sans-serif;
      margin: 0 0 16px;
      font-size: 18px;
      font-weight: 600;
      letter-spacing: 0.3px;
      color: #fff;
    }}
    h3 {{
      font-family: 'Outfit', sans-serif;
      margin: 0 0 12px;
      font-size: 15px;
      font-weight: 600;
      color: #fff;
    }}
    .website-board {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(130px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }}
    .website-tile {{
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      min-height: 104px;
      padding: 14px;
      background: var(--card-bg);
      backdrop-filter: blur(12px);
      border: 1px solid var(--border);
      border-radius: 12px;
      color: var(--text);
      text-decoration: none;
      transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }}
    .website-tile:hover {{
      background: var(--card-hover);
      border-color: rgba(99, 102, 241, 0.3);
      transform: translateY(-2px);
      box-shadow: 0 8px 24px rgba(0, 0, 0, 0.3);
    }}
    .website-tile.active {{
      background: linear-gradient(135deg, rgba(99, 102, 241, 0.25) 0%, rgba(79, 70, 229, 0.1) 100%);
      border-color: var(--primary);
      box-shadow: 0 0 16px rgba(99, 102, 241, 0.25);
    }}
    .tile-id {{
      font-family: 'Outfit', sans-serif;
      font-size: 15px;
      font-weight: 700;
      color: #fff;
      overflow-wrap: anywhere;
    }}
    .tile-name {{
      font-size: 12px;
      color: var(--text-muted);
      margin-top: 4px;
      overflow-wrap: anywhere;
    }}
    .tile-meta {{
      font-size: 11px;
      color: var(--cyan);
      margin-top: 12px;
      font-weight: 500;
    }}
    .top-grid {{
      display: grid;
      grid-template-columns: 300px 1fr;
      gap: 20px;
      align-items: start;
    }}
    .website-selector, .overview-hint, .website-detail, .import-panel, details {{
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
    }}
    .clear-filter {{
      display: inline-block;
      margin-left: 10px;
      font-size: 13px;
      color: var(--cyan);
      text-decoration: none;
      font-weight: 500;
    }}
    .clear-filter:hover {{
      text-decoration: underline;
    }}
    .scope-bar {{
      display: flex;
      align-items: center;
      gap: 10px;
      flex-wrap: wrap;
      margin: 0 0 16px;
      font-size: 13px;
      color: var(--text-muted);
    }}
    .scope-bar strong {{
      color: #fff;
      font-weight: 600;
    }}
    table {{
      border-collapse: separate;
      border-spacing: 0;
      width: 100%;
      margin-bottom: 16px;
      background: rgba(7, 10, 19, 0.4);
      border: 1px solid var(--border);
      border-radius: 10px;
      overflow: hidden;
    }}
    th, td {{
      border-bottom: 1px solid var(--border);
      padding: 12px 16px;
      text-align: left;
      vertical-align: middle;
      font-size: 13.5px;
    }}
    th {{
      background: rgba(15, 23, 42, 0.5);
      color: #fff;
      font-weight: 600;
      font-size: 12px;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    tr:last-child td {{
      border-bottom: none;
    }}
    tr:hover td {{
      background: rgba(255, 255, 255, 0.015);
    }}
    form {{
      display: grid;
      gap: 14px;
    }}
    label {{
      display: grid;
      gap: 6px;
      font-size: 12.5px;
      color: var(--text-muted);
      font-weight: 500;
    }}
    input, button, select {{
      font-family: inherit;
      padding: 10px 14px;
      border: 1px solid var(--border);
      background: rgba(7, 10, 19, 0.6);
      color: #fff;
      border-radius: 8px;
      font-size: 14px;
      transition: all 0.2s;
      outline: none;
      min-width: 0;
    }}
    input:focus, select:focus {{
      border-color: var(--primary);
      box-shadow: 0 0 0 3px var(--primary-glow);
    }}
    input[type="file"] {{
      background: rgba(255, 255, 255, 0.02);
      cursor: pointer;
    }}
    button {{
      background: linear-gradient(135deg, var(--primary) 0%, #4f46e5 100%);
      color: white;
      border: none;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 12px var(--primary-glow);
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 8px;
    }}
    button:hover {{
      transform: translateY(-1px);
      box-shadow: 0 6px 18px rgba(99, 102, 241, 0.55);
    }}
    button:active {{
      transform: translateY(0);
    }}
    button.secondary, button[data-close], button.close-btn-sm {{
      background: rgba(255, 255, 255, 0.08);
      border: 1px solid var(--border);
      color: var(--text);
      box-shadow: none;
    }}
    button.secondary:hover, button[data-close]:hover, button.close-btn-sm:hover {{
      background: rgba(255, 255, 255, 0.15);
      border-color: var(--border-hover);
    }}
    .import-grid {{
      display: grid;
      grid-template-columns: 1fr 1.5fr 1fr 1fr auto;
      gap: 14px;
      align-items: end;
    }}
    .status-line {{
      min-height: 20px;
      color: var(--cyan);
      font-size: 13.5px;
      margin-top: 12px;
      font-weight: 500;
    }}
    .advanced-grid {{
      display: grid;
      grid-template-columns: repeat(3, 1fr) auto;
      gap: 14px;
      align-items: end;
      padding: 10px 0;
    }}
    details {{
      padding: 14px 20px;
    }}
    details[open] summary {{
      margin-bottom: 16px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 10px;
    }}
    summary {{
      cursor: pointer;
      font-weight: 600;
      color: #fff;
      font-size: 14.5px;
      outline: none;
      user-select: none;
    }}
    summary:hover {{
      color: var(--cyan);
    }}
    .website-detail {{
      display: grid;
      grid-template-columns: minmax(0, 1fr) minmax(300px, 352px);
      gap: 20px;
      padding: 0;
      background: none;
      border: none;
      min-width: 0;
    }}
    .machine-rail {{
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
      display: flex;
      flex-direction: column;
      gap: 16px;
    }}
    .fleet-panel {{
      min-width: 0;
    }}
    .fleet-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
      gap: 14px;
    }}
    .machine-list {{
      display: grid;
      gap: 12px;
    }}
    .machine-card, .machine-empty {{
      background: rgba(7, 10, 19, 0.4);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 14px;
      text-decoration: none;
      color: inherit;
      display: grid;
      gap: 8px;
      transition: all 0.2s;
    }}
    .machine-card:hover {{
      background: rgba(255, 255, 255, 0.02);
      border-color: rgba(255, 255, 255, 0.15);
      transform: translateY(-1px);
    }}
    .machine-card.status-ok {{ border-left: 4px solid var(--ok); }}
    .machine-card.status-warning {{ border-left: 4px solid var(--warning); }}
    .machine-card.status-problem {{ border-left: 4px solid var(--problem); }}
    .machine-card.status-critical {{ border-left: 4px solid var(--critical); }}
    .machine-card.status-nodata {{ border-left: 4px solid var(--nodata); }}
    .machine-head {{
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 10px;
    }}
    .machine-name {{
      font-weight: 700;
      font-size: 15px;
      color: #fff;
      overflow-wrap: anywhere;
    }}
    .machine-role {{
      color: var(--text-muted);
      font-size: 12px;
      margin-top: 2px;
    }}
    .status-badge {{
      display: inline-block;
      border-radius: 6px;
      padding: 3px 8px;
      font-size: 10.5px;
      font-weight: 600;
      white-space: nowrap;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .status-ok {{
      background: rgba(16, 185, 129, 0.12);
      color: var(--ok);
      border: 1px solid rgba(16, 185, 129, 0.25);
    }}
    .status-warning {{
      background: rgba(245, 158, 11, 0.12);
      color: var(--warning);
      border: 1px solid rgba(245, 158, 11, 0.25);
    }}
    .status-problem {{
      background: rgba(239, 68, 68, 0.12);
      color: var(--problem);
      border: 1px solid rgba(239, 68, 68, 0.25);
    }}
    .status-critical {{
      background: rgba(236, 72, 153, 0.15);
      color: var(--critical);
      border: 1px solid rgba(236, 72, 153, 0.3);
    }}
    .status-nodata {{
      background: rgba(100, 116, 139, 0.12);
      color: var(--nodata);
      border: 1px solid rgba(100, 116, 139, 0.25);
    }}
    .machine-meta {{
      display: grid;
      gap: 5px;
      font-size: 12px;
      color: var(--text);
    }}
    .machine-latest {{
      border-top: 1px solid var(--border);
      padding-top: 10px;
      display: grid;
      gap: 5px;
      font-size: 12px;
      color: var(--text-muted);
    }}
    .machine-latest strong {{
      color: #fff;
      font-size: 12px;
      font-weight: 600;
    }}
    .machine-meta span {{
      color: var(--text-muted);
    }}
    .detail-column {{
      display: grid;
      gap: 20px;
      align-content: start;
      min-width: 0;
    }}
    .website-summary, .incident-panel, .log-panel {{
      border: 1px solid var(--border);
      border-radius: 14px;
      padding: 20px;
      background: var(--card-bg);
      min-width: 0;
    }}
    .incident-panel, .log-panel {{
      overflow-x: auto;
    }}
    .ai-side-panel {{
      border: 1px solid rgba(99, 102, 241, 0.28);
      border-radius: 14px;
      padding: 18px;
      background: linear-gradient(180deg, rgba(49, 46, 129, 0.46), rgba(15, 23, 42, 0.72));
      box-shadow: 0 0 28px rgba(99, 102, 241, 0.12);
      align-self: start;
      position: sticky;
      top: 94px;
      display: grid;
      gap: 14px;
    }}
    .ai-side-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 12px;
    }}
    .ai-side-head h2 {{
      margin: 0;
    }}
    .ai-box {{
      background: rgba(7, 10, 19, 0.55);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      display: grid;
      gap: 8px;
    }}
    .ai-box h3 {{
      margin: 0;
      font-size: 13px;
      color: #fff;
    }}
    .ai-box p {{
      margin: 0;
      color: #cbd5e1;
      font-size: 13px;
      line-height: 1.45;
    }}
    .evidence-line {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 11.5px;
      color: #cbd5e1;
      border-top: 1px solid var(--border);
      padding-top: 8px;
      word-break: break-word;
    }}
    .detail-head {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      flex-wrap: wrap;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
      margin-bottom: 16px;
    }}
    .detail-head h2 {{
      margin: 0;
      font-size: 22px;
    }}
    .detail-head .scope-bar {{
      margin: 4px 0 0;
    }}
    .ai-btn {{
      background: linear-gradient(135deg, var(--primary) 0%, #4f46e5 100%);
      color: white;
      border: none;
      padding: 10px 18px;
      border-radius: 8px;
      font-size: 13.5px;
      font-weight: 600;
      cursor: pointer;
      box-shadow: 0 4px 12px var(--primary-glow);
      transition: all 0.2s;
      display: inline-flex;
      align-items: center;
      gap: 8px;
    }}
    .ai-btn:hover {{
      transform: translateY(-1px);
      box-shadow: 0 6px 18px rgba(99, 102, 241, 0.5);
    }}
    .ai-btn-sm {{
      background: rgba(99, 102, 241, 0.15);
      border: 1px solid rgba(99, 102, 241, 0.3);
      color: #a5b4fc;
      padding: 4px 10px;
      border-radius: 6px;
      font-size: 11px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.2s;
    }}
    .ai-btn-sm:hover {{
      background: var(--primary);
      color: white;
      box-shadow: 0 0 10px var(--primary-glow);
    }}
    .muted {{
      color: var(--text-muted);
      font-size: 13px;
    }}
    .log-panel table {{
      margin-bottom: 0;
    }}
    .log-message {{
      font-family: 'JetBrains Mono', monospace;
      font-size: 12.5px;
      color: #cbd5e1;
      word-break: break-all;
    }}
    .log-time {{
      font-family: monospace;
      font-size: 12px;
      color: var(--text-muted);
      white-space: nowrap;
    }}
    .log-cat {{
      font-family: monospace;
      font-weight: 500;
      color: var(--cyan);
    }}
    .modal-overlay {{
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      bottom: 0;
      background: rgba(7, 10, 19, 0.85);
      backdrop-filter: blur(8px);
      display: flex;
      align-items: center;
      justify-content: center;
      z-index: 1000;
      padding: 20px;
      animation: fade-in 0.25s ease-out;
    }}
    .modal-card {{
      background: #0f1524;
      border: 1px solid rgba(255, 255, 255, 0.08);
      border-radius: 16px;
      width: 100%;
      max-width: 800px;
      max-height: 85vh;
      box-shadow: 0 25px 50px -12px rgba(0, 0, 0, 0.5);
      display: flex;
      flex-direction: column;
      overflow: hidden;
      animation: slide-up 0.3s cubic-bezier(0.34, 1.56, 0.64, 1);
    }}
    .modal-header {{
      padding: 20px 24px;
      border-bottom: 1px solid var(--border);
      display: flex;
      justify-content: space-between;
      align-items: center;
    }}
    .modal-header h3 {{
      font-family: 'Outfit', sans-serif;
      font-size: 18px;
      margin: 0;
      color: #fff;
    }}
    .close-btn {{
      background: none;
      border: none;
      color: var(--text-muted);
      font-size: 24px;
      cursor: pointer;
      line-height: 1;
    }}
    .close-btn:hover {{
      color: #fff;
    }}
    .modal-body {{
      padding: 24px;
      overflow-y: auto;
      flex-grow: 1;
    }}
    .ai-loading {{
      display: flex;
      flex-direction: column;
      align-items: center;
      justify-content: center;
      padding: 40px 0;
      gap: 16px;
    }}
    .spinner {{
      width: 40px;
      height: 40px;
      border: 3px solid rgba(99, 102, 241, 0.1);
      border-top-color: var(--primary);
      border-radius: 50%;
      animation: spin 1s infinite linear;
    }}
    @keyframes spin {{
      0% {{ transform: rotate(0deg); }}
      100% {{ transform: rotate(360deg); }}
    }}
    .ai-report {{
      display: grid;
      gap: 20px;
    }}
    .report-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      padding-bottom: 16px;
      border-bottom: 1px solid var(--border);
    }}
    .report-meta {{
      font-size: 13px;
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--text-muted);
    }}
    .meta-separator {{
      opacity: 0.3;
    }}
    .confidence-container {{
      display: flex;
      align-items: center;
      gap: 10px;
      font-size: 13px;
    }}
    .progress-bar {{
      width: 100px;
      height: 6px;
      background: rgba(255, 255, 255, 0.05);
      border-radius: 3px;
      overflow: hidden;
    }}
    .progress-fill {{
      height: 100%;
      background: linear-gradient(90deg, var(--primary) 0%, var(--cyan) 100%);
      border-radius: 3px;
    }}
    .confidence-val {{
      font-weight: 600;
      color: var(--cyan);
    }}
    .report-section {{
      background: rgba(7, 10, 19, 0.4);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 16px;
    }}
    .highlight-box {{
      border-color: rgba(99, 102, 241, 0.2);
      background: rgba(99, 102, 241, 0.03);
      box-shadow: inset 0 0 12px rgba(99, 102, 241, 0.02);
    }}
    .report-section h4 {{
      font-family: 'Outfit', sans-serif;
      font-size: 14px;
      margin-bottom: 10px;
      color: #fff;
      text-transform: uppercase;
      letter-spacing: 0.5px;
    }}
    .report-text {{
      font-size: 14px;
      line-height: 1.6;
      color: var(--text);
    }}
    .summary-text {{
      font-size: 14.5px;
      line-height: 1.7;
      color: #e2e8f0;
    }}
    .report-grid {{
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 16px;
    }}
    .evidence-details {{
      background: rgba(7, 10, 19, 0.6);
      border: 1px solid var(--border);
      border-radius: 10px;
      padding: 12px;
      margin-top: 10px;
    }}
    .evidence-details summary {{
      font-size: 13px;
      color: var(--text-muted);
      font-weight: 500;
    }}
    .evidence-list {{
      margin-top: 14px;
      display: grid;
      gap: 10px;
    }}
    .evidence-list h5 {{
      font-size: 12px;
      color: var(--text-muted);
      text-transform: uppercase;
    }}
    .agent-pills {{
      display: flex;
      flex-wrap: wrap;
      gap: 6px;
    }}
    .agent-pill {{
      font-family: monospace;
      font-size: 11px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border);
      padding: 3px 8px;
      border-radius: 4px;
      color: #fff;
    }}
    .evidence-pre {{
      background: #04060a;
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 12px;
      font-family: 'JetBrains Mono', monospace;
      font-size: 11px;
      overflow-x: auto;
      color: #94a3b8;
      max-height: 250px;
      line-height: 1.5;
    }}
    @keyframes fade-in {{
      from {{ opacity: 0; }}
      to {{ opacity: 1; }}
    }}
    @keyframes slide-up {{
      from {{ transform: translateY(20px); opacity: 0; }}
      to {{ transform: translateY(0); opacity: 1; }}
    }}
    @media (max-width: 1024px) {{
      .ops-shell {{ grid-template-columns: 1fr; }}
      .sidebar {{ position: static; height: auto; flex-direction: row; flex-wrap: wrap; }}
      .sidebar-footer {{ display: none; }}
      main {{ padding: 16px; }}
      .top-grid, .website-detail, .import-grid, .advanced-grid {{ grid-template-columns: 1fr; }}
      .website-detail {{ grid-template-columns: 1fr; }}
      .ai-side-panel {{ position: static; }}
      th, td {{ padding: 10px 12px; font-size: 13px; }}
    }}
  </style>
</head>
<body>
  <div class="ops-shell">
    <aside class="sidebar">
      <div class="brand-mark"><span class="brand-icon">AI</span><span>AI Log Monitor</span></div>
      <nav class="nav-list">
        <a class="nav-item active" href="/">▦ Overview</a>
        <a class="nav-item" href="#log-panel">☰ Log Explorer</a>
        <a class="nav-item" href="#incidents-panel">△ Incidents</a>
        <a class="nav-item" href="#agents-table">◎ Agents</a>
      </nav>
      <div class="sidebar-footer">
        <strong>Scope</strong><br>
        {_h(selected_label)}<br>
        {len(agents)} connected host(s)
      </div>
    </aside>
    <div class="workspace">
  <header>
    <div class="header-container">
      <div class="logo">
        <span class="pulse-dot"></span>
        <h1>AI Log Monitor</h1>
      </div>
      <div class="header-status">
        <span class="status-indicator">SYSTEM ONLINE</span>
      </div>
    </div>
  </header>
  <main>
    <div class="top-grid">
      <section class="website-selector">
        <h2>Operational Scopes</h2>
        <div class="scope-bar"><strong>Selected Website: {_h(selected_label)}</strong>{clear_filter_link}</div>
        <div class="website-board">{website_cards}</div>
      </section>
      {detail_panel}
    </div>
    
    <section class="import-panel">
      <h2>Manual Ingest Portal</h2>
      <form id="file-import">
        <div class="import-grid">
          <label>Target Website<input name="website_id" list="website-options" value="{_h(selected_website_id or 'website_1')}" required></label>
          <label>Select Log File<input name="log_file" type="file" required></label>
          <label>Source Identifier<input name="agent_id" value="manual_upload" required></label>
          <label>Agent Role<input name="agent_role" value="manual"></label>
          <button type="submit">Ingest Log File</button>
        </div>
        <input name="log_type" type="hidden" value="uploaded_file">
        <datalist id="website-options">{website_options}</datalist>
      </form>
      <div id="import-status" class="status-line"></div>
    </section>
    
    <section class="data-shell">
      <details>
        <summary>Advanced Admin Options</summary>
        <div style="display: grid; gap: 16px; margin-top: 14px;">
          <form id="create-website" class="advanced-grid">
            <strong style="color: #fff;">Register Website</strong>
            <label>Website ID<input name="website_id" placeholder="website_1" required></label>
            <label>Friendly Name<input name="name" placeholder="Website Name" required></label>
            <button type="submit" class="secondary">Create Website</button>
          </form>
          <form id="assign-agent" class="advanced-grid">
            <strong style="color: #fff;">Bind Agent</strong>
            <label>Agent ID<input name="agent_id" placeholder="web01" required></label>
            <label>Website ID<input name="website_id" placeholder="website_1" required></label>
            <label>Agent Role<input name="agent_role" placeholder="web"></label>
            <button type="submit" class="secondary">Bind Agent</button>
          </form>
        </div>
      </details>
    </section>
    
    <section class="data-shell">
      <details>
        <summary>Database Explorer Tables</summary>
        <div style="margin-top: 14px; overflow-x: auto;">
          <h3>Websites DB</h3>
          <table>
            <thead><tr><th>Website ID</th><th>Name</th><th>Status</th><th>Created</th></tr></thead>
            <tbody>{website_rows or '<tr><td colspan="4">No websites registered</td></tr>'}</tbody>
          </table>
          <h3>Agents Registry</h3>
          <table id="agents-table">
            <thead><tr><th>Agent</th><th>Website</th><th>Role</th><th>Status</th><th>Hostname</th><th>Last Seen</th></tr></thead>
            <tbody>{agent_rows or '<tr><td colspan="6">No agents connected</td></tr>'}</tbody>
          </table>
          <h3>Incidents DB</h3>
          <table>
            <thead><tr><th>Website</th><th>Severity</th><th>Status</th><th>Title</th><th>Events</th><th>Last Seen</th><th>Action</th></tr></thead>
            <tbody>{incident_rows or '<tr><td colspan="7">No operational incidents logged</td></tr>'}</tbody>
          </table>
          <h3>Live Log Feed</h3>
          <table>
            <thead><tr><th>Website</th><th>Agent</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead>
            <tbody>{event_rows or '<tr><td colspan="5">No events logged</td></tr>'}</tbody>
          </table>
        </div>
      </details>
    </section>
  </main>
    </div>
  </div>
  
  <!-- AI Diagnostics Modal -->
  <div id="ai-modal" class="modal-overlay" style="display: none;">
    <div class="modal-card">
      <div class="modal-header">
        <h3>✨ AI Operations Analysis</h3>
        <button class="close-btn" onclick="closeAiModal()">&times;</button>
      </div>
      <div class="modal-body" id="ai-modal-content">
        <!-- Content inserted dynamically -->
      </div>
    </div>
  </div>

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
      status.textContent = 'Uploading and processing log data...';
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
      status.textContent = `Import complete: processed ${{result.imported_lines}} log lines (${{result.problem_lines}} issues found).`;
      setTimeout(() => location.reload(), 800);
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
    
    async function runAiAnalysis(websiteId) {{
      const panelContent = document.getElementById('ai-panel-content');
      const modal = document.getElementById('ai-modal');
      const content = panelContent || document.getElementById('ai-modal-content');
      if (!panelContent) {{
        modal.style.display = 'flex';
      }}
      content.innerHTML = `
        <div class="ai-loading">
          <div class="spinner"></div>
          <p style="color: var(--text-muted); font-size: 14px;">Analyzing logs with Ollama AI model (qwen2.5:3b)...</p>
        </div>
      `;
      try {{
        const response = await fetch(`/api/analyze?website_id=${{encodeURIComponent(websiteId)}}`);
        const result = await response.json();
        if (!response.ok) {{
          content.innerHTML = `<div class="status-badge status-critical" style="padding: 12px; border-radius: 8px; width: 100%; display: block; text-align: center;">Analysis failed: ${{result.error || 'Unknown error'}}</div>`;
          return;
        }}
        
        let matchedBadge = '';
        if (result.memory_status === 'matched') {{
          matchedBadge = '<span class="status-badge status-ok">Known Incident Matched</span>';
        }} else if (result.memory_status === 'stored') {{
          matchedBadge = '<span class="status-badge status-warning">Pattern Registered to Memory</span>';
        }}

        content.innerHTML = `
          <div class="ai-report">
            <div class="report-header">
              <div class="report-meta">
                <span class="meta-label">Website ID:</span> <strong style="color: var(--cyan);">${{escapeHtml(result.website_id)}}</strong>
                <span class="meta-separator">|</span>
                <span class="meta-label">Engine:</span> <span>${{escapeHtml(result.provider)}} (${{escapeHtml(result.mode)}})</span>
                ${{matchedBadge}}
              </div>
              <div class="confidence-container">
                <span style="color: var(--text-muted);">Confidence:</span>
                <div class="progress-bar">
                  <div class="progress-fill" style="width: ${{Math.round(result.confidence * 100)}}%;"></div>
                </div>
                <span class="confidence-val">${{Math.round(result.confidence * 100)}}%</span>
              </div>
            </div>
            
            <div class="report-section highlight-box">
              <h4 style="color: var(--cyan);">💡 Summary & Insights (ภาษาไทย)</h4>
              <div class="report-text summary-text">${{escapeHtml(result.summary).replace(/\\n/g, '<br>')}}</div>
            </div>

            <div class="report-grid">
              <div class="report-section">
                <h4 style="color: #fca5a5;">🔍 Root Cause Analysis</h4>
                <p class="report-text">${{escapeHtml(result.root_cause)}}</p>
              </div>
              <div class="report-section">
                <h4 style="color: #a7f3d0;">🚀 Recommended Countermeasure</h4>
                <p class="report-text">${{escapeHtml(result.recommended_action)}}</p>
              </div>
            </div>

            <details class="evidence-details">
              <summary>View Diagnostic Context (${{result.evidence ? result.evidence.length : 0}} log entries analyzed)</summary>
              <div class="evidence-list" style="margin-top: 12px;">
                <h5>Checked Agents:</h5>
                <div class="agent-pills">
                  ${{result.agents_checked ? result.agents_checked.map(a => `<span class="agent-pill">${{escapeHtml(a)}}</span>`).join('') : '<span class="muted">None</span>'}}
                </div>
                <h5 style="margin-top: 14px;">Recent Problems Context:</h5>
                <pre class="evidence-pre">${{result.evidence ? result.evidence.map(e => escapeHtml(e)).join('\\n') : 'No recent errors in log history.'}}</pre>
              </div>
            </details>
          </div>
        `;
      }} catch (err) {{
        content.innerHTML = `<div class="status-badge status-critical" style="padding: 12px; border-radius: 8px; width: 100%; display: block; text-align: center;">Error: ${{err.message || err}}</div>`;
      }}
    }}

    function closeAiModal() {{
      document.getElementById('ai-modal').style.display = 'none';
    }}

    function escapeHtml(str) {{
      if (!str) return '';
      return str.toString()
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
    }}
  </script>
</body>
</html>"""


def _render_empty_dashboard() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Log Monitor - Waiting</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&family=Outfit:wght@600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      --bg: #070a13;
      --card-bg: rgba(15, 23, 42, 0.6);
      --border: rgba(255, 255, 255, 0.08);
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --primary: #6366f1;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: 'Inter', sans-serif;
      background: radial-gradient(circle at center, #0f172a 0%, var(--bg) 100%);
      color: var(--text);
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 24px;
    }
    .empty-dashboard {
      text-align: center;
      max-width: 480px;
      padding: 40px;
      background: var(--card-bg);
      backdrop-filter: blur(16px);
      border: 1px solid var(--border);
      border-radius: 16px;
      box-shadow: 0 20px 40px rgba(0, 0, 0, 0.3);
    }
    .radar-circle {
      position: relative;
      width: 100px;
      height: 100px;
      margin: 0 auto 30px;
      border: 2px solid rgba(99, 102, 241, 0.2);
      border-radius: 50%;
      display: grid;
      place-items: center;
    }
    .radar-circle::before {
      content: '';
      position: absolute;
      width: 100%;
      height: 100%;
      border: 2px solid var(--primary);
      border-radius: 50%;
      animation: pulse 2s infinite ease-out;
      opacity: 0;
    }
    .radar-core {
      width: 16px;
      height: 16px;
      background: var(--primary);
      border-radius: 50%;
      box-shadow: 0 0 16px var(--primary);
    }
    h2 {
      font-family: 'Outfit', sans-serif;
      font-size: 22px;
      margin-bottom: 12px;
      letter-spacing: 0.5px;
      color: #fff;
    }
    p {
      color: var(--text-muted);
      font-size: 14px;
      line-height: 1.6;
      margin-bottom: 24px;
    }
    .status-badge {
      display: inline-block;
      padding: 6px 12px;
      background: rgba(255, 255, 255, 0.05);
      border: 1px solid var(--border);
      border-radius: 20px;
      font-size: 12px;
      font-family: monospace;
      color: #06b6d4;
    }
    @keyframes pulse {
      0% { transform: scale(0.6); opacity: 1; }
      100% { transform: scale(1.6); opacity: 0; }
    }
  </style>
</head>
<body>
  <div class="empty-dashboard">
    <div class="radar-circle">
      <div class="radar-core"></div>
    </div>
    <h2>Waiting for agent connection</h2>
    <p>The AI Log Monitor server is active and listening on port 8888. Please install and launch an agent on your client machines to begin streaming operations logs.</p>
    <div class="status-badge">status: listening_on_port_8888</div>
  </div>
</body>
</html>"""


def _render_overview_hint(events: list[dict[str, Any]]) -> str:
    problem_count = sum(1 for event in events if event["severity"] in {"warning", "problem", "critical"})
    return f"""
      <section class="overview-hint">
        <h2>System Summary</h2>
        <p class="muted">Select an operational scope (website) from the panel on the left to review isolated logs and launch AI diagnostics.</p>
        <div class="metric-row">
          <div class="metric"><strong>{len(events)}</strong><span>recent log entries</span></div>
          <div class="metric"><strong>{problem_count}</strong><span>unhandled warnings/errors</span></div>
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
        f"<tr><td><span class='status-badge {_severity_badge_class(incident['severity'])}'>{_h(incident['severity'])}</span></td>"
        f"<td><span class='status-badge {_severity_badge_class('warning' if incident['status']=='open' else 'ok')}'>{_h(incident['status'])}</span></td>"
        f"<td><strong style='color:#fff;'>{_h(incident['title'])}</strong></td><td>{incident['event_count']}</td>"
        f"<td class='log-time'>{_h(incident['last_seen_at'])}</td>"
        f"<td><button class='close-btn-sm' data-close='{_h(incident['incident_id'])}'>Close</button></td></tr>"
        for incident in incidents
    )
    event_rows = "\n".join(
        f"<tr><td class='log-time'>{_h(event['timestamp'])}</td><td><strong>{_h(event['agent_id'])}</strong></td>"
        f"<td><span class='status-badge {_severity_badge_class(str(event['severity']))}'>{_h(event['severity'])}</span></td>"
        f"<td class='log-cat'>{_h(event['category'])}</td><td class='log-message'>{_h(event['message'])}</td></tr>"
        for event in events
    )
    return f"""
      <section class="website-detail">
        <div class="detail-column">
          <section class="website-summary">
            <div class="detail-head">
              <div>
                <h2>{_h(selected_website_id)}</h2>
                <div class="scope-bar"><strong>Selected Website: {_h(selected_website_id)}</strong></div>
              </div>
              <button class="ai-btn" onclick="runAiAnalysis('{_h(selected_website_id)}')">✨ Run AI Diagnostics</button>
            </div>
            <div class="metric-row">
              <div class="metric"><strong>{len(agents)}</strong><span>connected hosts</span></div>
              <div class="metric"><strong>{len(open_incidents)}</strong><span>open incidents</span></div>
              <div class="metric"><strong>{len(problem_events)}</strong><span>problem logs</span></div>
              <div class="metric"><strong>{len(critical_events)}</strong><span>critical logs</span></div>
            </div>
            <p class="muted" style="margin-top: 14px;">Latest operational signal: <strong style="color: var(--cyan);">{_h(latest_label)}</strong></p>
          </section>
          {_render_machine_monitor(agents, events, selected_website_id)}
          <section class="incident-panel" id="incidents-panel">
            <h2>Active Incidents</h2>
            <table>
              <thead><tr><th>Severity</th><th>Status</th><th>Incident Title</th><th>Events Count</th><th>Last Active</th><th>Action</th></tr></thead>
              <tbody>{incident_rows or '<tr><td colspan="6">No registered incidents in this scope</td></tr>'}</tbody>
            </table>
          </section>
          <section class="log-panel" id="log-panel">
            <h2>Operations Log Stream</h2>
            <table>
              <thead><tr><th>Ingest Time</th><th>Machine</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead>
              <tbody>{event_rows or '<tr><td colspan="5">No operations logs registered</td></tr>'}</tbody>
            </table>
          </section>
        </div>
        {_render_ai_side_panel(agents, incidents, events, selected_website_id)}
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
        latest_message = latest_event["message"] if latest_event else "No log evidence yet"
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
          <div><span>Host:</span> {_h(hostname)}</div>
          <div><span>Signal:</span> {_h(last_signal)}</div>
          <div><span>Type:</span> {_h(last_category)}</div>
          <div><span>Errors:</span> {_h(problem_count)}</div>
        </div>
        <div class="machine-latest">
          <strong>Latest Incident</strong>
          <div>{_h(latest_message)}</div>
        </div>
      </a>""".rstrip()
        )

    body = "\n".join(cards) if cards else '<div class="machine-empty">No active agents bound to this scope.</div>'
    return f"""
    <section class="machine-rail">
      <h2>Server Fleet Status</h2>
      <div class="muted">Machine Monitor</div>
      <div class="fleet-panel">
      <div class="fleet-grid">
{body}
      </div>
      </div>
    </section>"""


def _render_ai_side_panel(
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str,
) -> str:
    open_incidents = [incident for incident in incidents if incident.get("status") == "open"]
    primary_incident = open_incidents[0] if open_incidents else (incidents[0] if incidents else None)
    problem_events = [event for event in events if event["severity"] in {"warning", "problem", "critical"}]
    primary_event = problem_events[0] if problem_events else (events[0] if events else None)
    suspected_machine = (
        str(primary_incident.get("primary_agent_id") or "")
        if primary_incident
        else (str(primary_event.get("agent_id") or "") if primary_event else "-")
    )
    suspected_role = next(
        (str(agent.get("agent_role") or "-") for agent in agents if str(agent.get("agent_id")) == suspected_machine),
        str(primary_event.get("agent_role") or "-") if primary_event else "-",
    )
    incident_title = str(primary_incident.get("title") or "No active incident") if primary_incident else "No active incident"
    root_cause = (
        f"Most recent signal points to {_h(str(primary_event.get('category') or 'normal activity'))} on {_h(suspected_machine)}."
        if primary_event
        else "No problem evidence has arrived for this website yet."
    )
    evidence_lines = "\n".join(
        f"<div class='evidence-line'><strong>{_h(event['agent_id'])}</strong> {_h(event['severity'])}: {_h(event['message'])}</div>"
        for event in problem_events[:4]
    ) or "<p class='muted'>No problem log evidence in the current window.</p>"
    return f"""
        <aside class="ai-side-panel">
      <div class="ai-side-head">
        <h2>AI Summary Panel</h2>
        <button class="ai-btn-sm" onclick="runAiAnalysis('{_h(selected_website_id)}')">Analyze</button>
      </div>
      <div id="ai-panel-content" class="ai-box">
        <h3>Incident Insight</h3>
        <p>{_h(incident_title)}</p>
      </div>
      <div class="ai-box">
        <h3>Root Cause Analysis</h3>
        <p>{root_cause}</p>
      </div>
      <div class="ai-box">
        <h3>Suspected Machine</h3>
        <p><strong style="color: var(--cyan);">{_h(suspected_machine)}</strong> | {_h(suspected_role)} | {_h(selected_website_id)}</p>
        <a class="ai-btn-sm" href="#log-panel" style="text-decoration: none; width: fit-content;">View Logs</a>
      </div>
      <div class="ai-box">
        <h3>Log Evidence</h3>
        {evidence_lines}
      </div>
    </aside>""".rstrip()


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
