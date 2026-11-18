from __future__ import annotations

from pathlib import Path
from typing import Any
from urllib.parse import quote

from .utils import _compact_page_numbers, _h, _safe_filename, _safe_path_part, _safe_timestamp

LOG_PAGE_SIZE = 10
DASHBOARD_PAGES = {"overview", "website", "logs", "incidents", "agents", "settings", "import", "admin"}
PAGE_PATHS = {
    "overview": "/",
    "website": "/website",
    "logs": "/logs",
    "incidents": "/incidents",
    "agents": "/agents",
    "settings": "/settings",
    "import": "/import",
    "admin": "/admin",
}


def _overview_websites(
    websites: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return list(websites)

def _page_subtitle(page: str, website_id: str) -> str:
    subtitles = {
        "overview": "Status across all registered websites",
        "website": f"Isolated monitor for {website_id or 'the selected website'}",
        "logs": "Search and review collected problem evidence",
        "incidents": "",
        "agents": "Install and monitor connected machines",
        "settings": "AI analysis and system configuration",
        "import": "Import a log file into a selected website",
        "admin": "Advanced registration and database tools",
    }
    return subtitles.get(page, "AI Log Monitor")

def _selected(current: str, expected: str) -> str:
    return " selected" if current == expected else ""


def _relative_label(agents: list[dict[str, Any]]) -> str:
    if not agents:
        return "No data"
    ages = [agent.get("seconds_since_seen") for agent in agents if agent.get("seconds_since_seen") is not None]
    if not ages:
        return str(max((agent.get("last_seen_at") or "-" for agent in agents), default="-"))
    seconds = max(0, min(int(age) for age in ages))
    if seconds < 60:
        return "Less than a minute ago"
    if seconds < 3600:
        return f"{seconds // 60} minute(s) ago"
    if seconds < 86400:
        return f"{seconds // 3600} hour(s) ago"
    return f"{seconds // 86400} day(s) ago"


def _render_empty_dashboard() -> str:
    template_path = Path(__file__).resolve().parent / "templates" / "empty_dashboard.html"
    return template_path.read_text(encoding="utf-8")


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


def _dashboard_href(page: str, website_id: str = "", log_page: int | None = None) -> str:
    selected_page = page if page in DASHBOARD_PAGES else "overview"
    path = PAGE_PATHS[selected_page]
    query: list[str] = []
    if website_id:
        query.append(f"website_id={quote(website_id)}")
    if selected_page == "logs" and log_page and log_page > 1:
        query.append(f"log_page={log_page}")
    return path if not query else f"{path}?{'&'.join(query)}"


def _agent_detail_href(website_id: str, agent_id: str) -> str:
    return f"/website?website_id={quote(website_id)}&agent_id={quote(agent_id)}"


def _source_detail_href(website_id: str, agent_id: str, source_id: str) -> str:
    return f"{_agent_detail_href(website_id, agent_id)}&source_id={quote(source_id)}"


def _nav_href(page: str, selected_website_id: str) -> str:
    return _dashboard_href(page, selected_website_id)

def _severity_badge_class(severity: str) -> str:
    if severity == "critical":
        return "status-critical"
    if severity == "problem":
        return "status-problem"
    if severity == "warning":
        return "status-warning"
    return "status-ok"


def _source_status_class(status: str) -> str:
    normalized = status.lower()
    if normalized == "readable":
        return "status-ok"
    if normalized in {"missing", "directory"}:
        return "status-warning"
    return "status-problem"


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


def _render_log_message(message: Any) -> str:
    text = str(message)
    escaped = _h(text)
    if len(text) <= 180:
        return f'<span class="log-message-preview" title="{escaped}">{escaped}</span>'

    preview = text[:177].rstrip() + "..."
    return (
        '<details class="log-message-details">'
        f'<summary><span class="log-message-preview" title="{escaped}">{_h(preview)}</span></summary>'
        f'<pre class="log-message-full">{escaped}</pre>'
        "</details>"
    )


def _render_log_pagination(website_id: str, page: int, total_events: int) -> str:
    total_pages = max(1, (total_events + LOG_PAGE_SIZE - 1) // LOG_PAGE_SIZE)
    if total_pages <= 1:
        return ""

    current = min(max(1, page), total_pages)
    start_item = ((current - 1) * LOG_PAGE_SIZE) + 1
    end_item = min(total_events, current * LOG_PAGE_SIZE)

    def page_href(target: int) -> str:
        return _h(f"{_dashboard_href('logs', website_id, target)}#log-panel")

    prev_html = (
        f'<a class="page-btn" href="{page_href(current - 1)}">Prev</a>'
        if current > 1
        else '<span class="page-btn disabled">Prev</span>'
    )
    next_html = (
        f'<a class="page-btn" href="{page_href(current + 1)}">Next</a>'
        if current < total_pages
        else '<span class="page-btn disabled">Next</span>'
    )
    page_parts = []
    for index in _compact_page_numbers(current, total_pages):
        if index is None:
            page_parts.append('<span class="page-ellipsis">...</span>')
        else:
            page_parts.append(
                f'<a class="page-btn{" active" if index == current else ""}" href="{page_href(index)}">{index}</a>'
            )
    pages = "\n".join(page_parts)
    return f"""
            <nav class="log-pagination" aria-label="Operations log pages">
              <span>Page {current} of {total_pages} · Showing {start_item}-{end_item} of {total_events}</span>
              <div class="page-buttons">{prev_html}{pages}{next_html}</div>
            </nav>""".rstrip()
