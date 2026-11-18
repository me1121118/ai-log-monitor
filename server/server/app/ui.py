from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .ui_components import (
    _render_admin_panel, _render_agent_detail, _render_agents_panel,
    _render_import_panel, _render_incidents_panel, _render_log_panel,
    _render_mockup_overview, _render_mockup_website_detail,
    _render_settings_panel, _render_source_detail,
)
from .ui_helpers import (
    DASHBOARD_PAGES, LOG_PAGE_SIZE, PAGE_PATHS, _dashboard_href, _h,
    _overview_websites, _page_subtitle, _render_empty_dashboard,
    _render_log_message, _severity_badge_class,
)

def _render_dashboard(
    websites: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str = "",
    log_events: list[dict[str, Any]] | None = None,
    log_page: int = 1,
    total_log_events: int = 0,
    log_sources: list[dict[str, Any]] | None = None,
    topology_hints: list[dict[str, Any]] | None = None,
    settings: dict[str, Any] | None = None,
    page: str = "overview",
    public_url: str = "http://10.1.0.10:8888",
    selected_agent_id: str = "",
    selected_source_id: str = "",
    er_topology: dict[str, Any] | None = None,
    traffic_summary: dict[str, Any] | None = None,
    raw_source_logs: list[dict[str, Any]] | None = None,
) -> str:
    selected_page = page if page in DASHBOARD_PAGES else "overview"
    overview_websites = _overview_websites(websites, agents)
    if selected_website_id and selected_website_id not in {str(w["website_id"]) for w in websites}:
        return _render_empty_dashboard()
    log_sources = log_sources or []
    topology_hints = topology_hints or []
    settings = settings or {}
    page_path = PAGE_PATHS[selected_page]
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
           href="{_h(_dashboard_href(selected_page, website_id))}" data-website="{_h(website_id)}">
          <span class="tile-id">{_h(website_id)}</span>
          <span class="tile-name">{_h(website_names.get(website_id, website_id))}</span>
          <span class="tile-meta">{agents_by_website.get(website_id, 0)} host(s) / {incidents_by_website.get(website_id, 0)} open</span>
        </a>""".rstrip()
        for website_id in website_ids
    )
    selected_label = selected_website_id or "all"
    clear_filter_link = (
        f'<a class="clear-filter" href="{_h(page_path)}">All Websites</a>' if selected_website_id else ""
    )
    website_rows = "\n".join(
        f"<tr><td><a href='/?website_id={_h(w['website_id'])}' style='color: var(--cyan); font-weight: 600;'>{_h(w['website_id'])}</a></td>"
        f"<td>{_h(w['name'])}</td><td><span class='status-badge status-ok'>{_h(w['status'])}</span></td>"
        f"<td>{_h(w['created_at'])}</td></tr>"
        for w in websites
    )
    agent_rows = "\n".join(
        f"<tr><td><strong>{_h(a['agent_id'])}</strong></td><td>{_h(a.get('website_id') or '-')}</td>"
        f"<td><span style='font-family: monospace; opacity: 0.85;'>{_h(a['agent_role'])}</span></td>"
        f"<td><span class='status-badge {_severity_badge_class('ok' if a['status']=='online' else 'critical')}'>{_h(a['status'])}</span></td>"
        f"<td>{_h(a.get('hostname') or '-')}</td><td class='log-time'>{_h(a['last_seen_at'])}</td></tr>"
        for a in agents
    )
    incident_rows = "\n".join(
        f"<tr><td>{_h(i['website_id'])}</td><td><span class='status-badge {_severity_badge_class(str(i['severity']))}'>{_h(i['severity'])}</span></td>"
        f"<td><span class='status-badge {_severity_badge_class('warning' if i['status']=='open' else 'ok')}'>{_h(i['status'])}</span></td>"
        f"<td><strong>{_h(i['title'])}</strong></td><td>{i['event_count']}</td><td class='log-time'>{_h(i['last_seen_at'])}</td>"
        f"<td><button class='close-btn-sm' data-close='{_h(i['incident_id'])}'>Close</button> "
        f"<button class='ai-btn-sm' onclick=\"runAiAnalysis('{_h(i['website_id'])}')\">Analyze</button></td></tr>"
        for i in incidents
    )
    event_rows = "\n".join(
        f"<tr><td>{_h(e['website_id'])}</td><td>{_h(e['agent_id'])}</td>"
        f"<td><span class='status-badge {_severity_badge_class(str(e['severity']))}'>{_h(e['severity'])}</span></td>"
        f"<td class='log-cat'>{_h(e['category'])}</td><td class='log-message'>{_render_log_message(e['message'])}</td></tr>"
        for e in events
    )
    selected_agent: dict[str, Any] | None = None
    selected_source: dict[str, Any] | None = None
    if selected_page == "overview":
        overview_website_ids = {
            str(website["website_id"])
            for website in overview_websites
        }
        content_panel = _render_mockup_overview(
            overview_websites,
            [agent for agent in agents if str(agent.get("website_id") or "") in overview_website_ids],
            [incident for incident in incidents if str(incident.get("website_id") or "") in overview_website_ids],
            [event for event in events if str(event.get("website_id") or "") in overview_website_ids],
        )
    elif selected_page == "website":
        active_website_id = selected_website_id or (website_ids[0] if website_ids else "")
        selected_agent = next(
            (agent for agent in agents if str(agent.get("agent_id") or "") == selected_agent_id),
            None,
        )
        selected_source = next(
            (
                source
                for source in log_sources
                if str(source.get("agent_id") or "") == selected_agent_id
                and str(source.get("source_id") or "") == selected_source_id
            ),
            None,
        )
        if selected_agent and selected_source:
            content_panel = _render_source_detail(
                active_website_id,
                selected_agent,
                selected_source,
                log_events or [],
                log_page,
                total_log_events,
                raw_source_logs=raw_source_logs,
            )
        elif selected_agent:
            content_panel = _render_agent_detail(
                active_website_id,
                selected_agent,
                [source for source in log_sources if str(source.get("agent_id") or "") == selected_agent_id],
                [event for event in events if str(event.get("agent_id") or "") == selected_agent_id],
            )
        else:
            content_panel = _render_mockup_website_detail(
                agents,
                incidents,
                events,
                active_website_id,
                log_sources,
                topology_hints,
                er_topology=er_topology,
                traffic_summary=traffic_summary,
            )
    elif selected_page == "logs":
        content_panel = _render_log_panel(log_events or events, selected_website_id, log_page, total_log_events)
    elif selected_page == "incidents":
        content_panel = _render_incidents_panel(incidents, events)
    elif selected_page == "agents":
        content_panel = _render_agents_panel(agents, selected_website_id, public_url)
    elif selected_page == "import":
        content_panel = _render_import_panel(website_options, selected_website_id)
    elif selected_page == "admin":
        content_panel = _render_admin_panel(website_rows, agent_rows, incident_rows, event_rows)
    else:
        content_panel = _render_settings_panel(settings)
    page_titles = {
        "overview": "Overview",
        "website": (
            f"Log Source: {selected_source.get('name')}" if selected_source
            else f"Machine: {selected_agent_id}" if selected_agent
            else f"Website Detail: {selected_website_id or (website_ids[0] if website_ids else '-')}"
        ),
        "logs": "Log Explorer",
        "incidents": "Incidents",
        "agents": "Agents",
        "import": "Manual Import",
        "settings": "Settings",
        "admin": "Advanced Admin",
    }
    page_title = page_titles[selected_page]
    active_website_ids = (
        [str(website["website_id"]) for website in overview_websites]
        if selected_page == "overview"
        else website_ids
    )
    active_website = selected_website_id or (active_website_ids[0] if active_website_ids else "")
    dashboard_shell = _render_app_shell(
        selected_page=selected_page,
        page_title=page_title,
        selected_website_id=active_website,
        content_panel=content_panel,
    )
    template_path = Path(__file__).resolve().parent / "templates" / "dashboard.html"
    html = template_path.read_text(encoding="utf-8")
    
    html = html.replace("{{dashboard_shell}}", dashboard_shell)
    return html


def _render_app_shell(
    selected_page: str,
    page_title: str,
    selected_website_id: str,
    content_panel: str,
) -> str:
    nav_items = [
        ("overview", "O", "Overview", _dashboard_href("overview")),
        ("website", "W", "Website Detail", _dashboard_href("website", selected_website_id)),
        ("logs", "L", "Log Explorer", _dashboard_href("logs", selected_website_id)),
        ("incidents", "I", "Incidents", _dashboard_href("incidents", selected_website_id)),
        ("agents", "A", "Agents", _dashboard_href("agents", selected_website_id)),
        ("settings", "S", "Settings", _dashboard_href("settings", selected_website_id)),
    ]
    nav = "\n".join(
        f'<a class="{"active" if page == selected_page else ""}" href="{_h(href)}"'
        f'{" style=\"display:none !important;\"" if page == "logs" else ""}>'
        f'<span class="nav-icon" aria-hidden="true">{icon}</span>{label}</a>'
        for page, icon, label, href in nav_items
    )
    return f"""
  <div class="dashboard-shell">
    <aside class="app-sidebar">
      <div class="brand-mark"><span class="brand-icon">ALM</span><span>AI Log Monitor</span></div>
      <nav class="app-nav">{nav}</nav>
      <div class="sidebar-footer">
        <a class="secondary-link" href="/login">Logout</a>
      </div>
    </aside>
    <main class="app-main">
      <header class="app-topbar">
        <div>
          <h1>{_h(page_title)}</h1>
          <p>{_h(_page_subtitle(selected_page, selected_website_id))}</p>
        </div>
        <div class="toolbar">
          <input id="global-search" class="search-box" type="search" placeholder="Search this page..." aria-label="Search this page">
          <button id="theme-toggle-btn" class="secondary" type="button" title="สลับโหมดมืด/สว่าง" onclick="toggleThemeMode()" style="min-height:38px;padding:0 12px;font-size:14px;">🌙 โหมดมืด</button>
          <button class="icon-button" type="button" title="Refresh" aria-label="Refresh" onclick="location.reload()">&#8635;</button>
        </div>
      </header>
      {content_panel}
    </main>
  </div>""".rstrip()
