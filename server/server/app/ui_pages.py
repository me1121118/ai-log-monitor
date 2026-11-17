from __future__ import annotations

from typing import Any

from .ui_helpers import (
    LOG_PAGE_SIZE, _agent_detail_href, _dashboard_href, _machine_status,
    _relative_label, _render_log_message, _render_log_pagination,
    _selected, _severity_badge_class, _source_detail_href, _source_status_class,
)
from .utils import _compact_page_numbers, _h

def _render_mockup_overview(
    websites: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    agents_by_website: dict[str, list[dict[str, Any]]] = {}
    active_agents_by_website: dict[str, list[dict[str, Any]]] = {}
    critical_by_website: dict[str, int] = {}
    warning_by_website: dict[str, int] = {}
    for agent in agents:
        website_id = str(agent.get("website_id") or "")
        agents_by_website.setdefault(website_id, []).append(agent)
        if str(agent.get("health_status") or agent.get("status") or "").lower() in {"active", "online"}:
            active_agents_by_website.setdefault(website_id, []).append(agent)
    for event in events:
        website_id = str(event.get("website_id") or "")
        if event.get("severity") == "critical":
            critical_by_website[website_id] = critical_by_website.get(website_id, 0) + 1
        if event.get("severity") in {"warning", "problem"}:
            warning_by_website[website_id] = warning_by_website.get(website_id, 0) + 1
    open_incidents_by_website: dict[str, list[dict[str, Any]]] = {}
    for incident in incidents:
        website_id = str(incident.get("website_id") or "")
        if website_id and incident.get("status") == "open":
            open_incidents_by_website.setdefault(website_id, []).append(incident)
    cards = []
    for index, website in enumerate(websites, start=1):
        website_id = str(website["website_id"])
        website_name = str(website.get("name") or website_id)
        name_sub = f' <span class="muted" style="font-weight:400;font-size:11px;">({_h(website_id)})</span>' if website_name != website_id else ""
        machine_count = len(agents_by_website.get(website_id, []))
        active_machine_count = len(active_agents_by_website.get(website_id, []))
        website_open_incidents = open_incidents_by_website.get(website_id, [])
        critical_count = sum(1 for incident in website_open_incidents if incident.get("severity") == "critical")
        warning_count = sum(1 for incident in website_open_incidents if incident.get("severity") in {"warning", "problem"})
        offline = active_machine_count == 0
        icon = "-" if offline else str(index)
        cards.append(
            f"""
        <div class="overview-card{' offline' if offline else ''}" style="position:relative;">
          <a href="{_h(_dashboard_href('website', website_id))}" style="text-decoration:none;color:inherit;display:block;">
            <div class="overview-card-head">
              <strong>{_h(website_name)}{name_sub}</strong>
              <span class="status-dot">{'Offline' if offline else 'Online'}</span>
            </div>
            <div class="overview-metrics">
              <div class="website-icon">{icon}</div>
              <dl>
                <div><dt>Machines</dt><dd><strong>{active_machine_count}/{machine_count}</strong></dd></div>
                <div><dt>Critical</dt><dd><span class="status-badge status-critical">{critical_count}</span></dd></div>
                <div><dt>Warning</dt><dd><span class="status-badge status-warning">{warning_count}</span></dd></div>
              </dl>
            </div>
          </a>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:8px;">
            <span class="muted">Last seen: {_h(_relative_label(agents_by_website.get(website_id, [])))}</span>
            <button type="button" class="er-vm-edit-btn" onclick="openWebsiteEditModal('{_h(website_id)}', '{_h(website_name)}')">✏️ แก้ไขชื่อ</button>
          </div>
        </div>""".rstrip()
        )
    online_websites = sum(1 for website in websites if active_agents_by_website.get(str(website["website_id"])))
    online_agents = sum(len(items) for items in active_agents_by_website.values())
    critical_total = sum(1 for incident in incidents if incident.get("severity") == "critical" and incident.get("status") == "open")
    warning_total = sum(1 for incident in incidents if incident.get("severity") in {"warning", "problem"} and incident.get("status") == "open")
    attention_rows = []
    for website_id, website_incidents in sorted(
        open_incidents_by_website.items(),
        key=lambda item: (len(item[1]), item[0]),
        reverse=True,
    ):
        latest = max(website_incidents, key=lambda incident: str(incident.get("last_seen_at") or ""))
        attention_rows.append(
            f"""
          <div class="attention-item">
            <div>
              <strong>{_h(website_id)}</strong>
              <span class="muted">{len(website_incidents)} open issue(s) · latest: {_h(latest.get('title') or latest.get('category') or 'problem')}</span>
            </div>
            <a class="attention-action" href="{_h(_dashboard_href('website', website_id))}">Open website monitor</a>
          </div>""".rstrip()
        )
    attention_panel = (
        f"""
      <section class="mock-panel attention-panel" hidden style="display:none !important;">
        <h2>Needs Attention</h2>
        <div class="attention-list">{''.join(attention_rows)}</div>
      </section>""".rstrip()
        if attention_rows
        else """
      <section class="mock-panel attention-panel" hidden style="display:none !important;">
        <h2>Needs Attention</h2>
        <p class="muted">No open incidents across monitored websites.</p>
      </section>""".rstrip()
    )
    return f"""
      <div style="display:flex;justify-content:flex-end;margin-bottom:12px;">
        <button type="button" class="secondary" onclick="openWebsiteEditModal('', '')" style="font-size:12.5px;padding:6px 12px;">+ เพิ่มวงเว็บไซต์ใหม่ (SIT / UAT / Production)</button>
      </div>
      <section class="overview-grid">{''.join(cards)}</section>
      <div id="website-edit-modal" class="modal-overlay" style="display:none;">
        <div class="modal-card" style="max-width:420px;">
          <div class="modal-header">
            <h3 id="website-edit-modal-title">✏️ แก้ไขชื่อเว็บไซต์ / วงระบบ</h3>
            <button type="button" class="close-btn" onclick="closeWebsiteEditModal()">&times;</button>
          </div>
          <div class="modal-body" id="website-edit-modal-body"></div>
        </div>
      </div>
      <section class="summary-strip" hidden style="display:none !important;">
        <div class="summary-item"><span class="summary-number">{online_agents}</span><span>Machines Online</span></div>
        <div class="summary-item"><span class="summary-number" style="color: var(--critical);">{critical_total}</span><span>Critical Issues</span></div>
        <div class="summary-item"><span class="summary-number" style="color: var(--warning);">{warning_total}</span><span>Warnings</span></div>
        <div class="summary-item"><span class="summary-number" style="color: var(--ok);">{online_websites}</span><span>Websites Online</span></div>
      </section>
      {attention_panel}""".rstrip()


def _render_mockup_website_detail(
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str,
    log_sources: list[dict[str, Any]] | None = None,
    topology_hints: list[dict[str, Any]] | None = None,
    er_topology: dict[str, Any] | None = None,
    traffic_summary: dict[str, Any] | None = None,
) -> str:
    log_sources = log_sources or []
    topology_hints = topology_hints or []
    problem_events = [event for event in events if event.get("severity") in {"warning", "problem", "critical"}]
    suspected = str(problem_events[0].get("agent_id")) if problem_events else "-"
    insight = _derive_dashboard_insight(problem_events)
    source_counts: dict[str, int] = {}
    for source in log_sources:
        agent_id = str(source.get("agent_id") or "")
        source_counts[agent_id] = source_counts.get(agent_id, 0) + 1
    fleet_cards = "\n".join(
        _render_fleet_mini_card(agent, events, selected_website_id, source_counts.get(str(agent.get("agent_id") or ""), 0))
        for agent in agents
    )
    problem_rows = "\n".join(
        f"<tr><td class='log-time' style='white-space:nowrap;'>{_h(event['timestamp'][:19].replace('T', ' '))}</td><td><strong>{_h(event['agent_id'])}</strong></td>"
        f"<td><span class='status-badge {_severity_badge_class(str(event['severity']))}'>{_h(event['severity'])}</span></td>"
        f"<td>{_h(event['category'])}</td><td class='log-message'>{_render_log_message(event['message'])}</td></tr>"
        for event in problem_events[:8]
    )
    online_count = sum(
        1 for a in agents
        if str(a.get("health_status") or a.get("status") or "").lower() in {"active", "online", "healthy"}
    )
    total_count = len(agents)
    anomalies_count = len(list((traffic_summary or {}).get("recent_anomalies") or []))
    traffic_badge_cls = "status-critical" if anomalies_count > 0 else "status-ok"
    traffic_badge_txt = f"พบความผิดปกติ {anomalies_count} รายการ" if anomalies_count > 0 else "ทราฟฟิกปกติ"

    return f"""
      <section class="website-summary-banner">
        <div class="summary-banner-item">
          <span class="muted">สถานะเครื่องในระบบ (Machines)</span>
          <strong>ออนไลน์ {online_count}/{total_count} เครื่อง</strong>
        </div>
        <div class="summary-banner-item">
          <span class="muted">ทราฟฟิก &amp; ความปลอดภัย (Traffic Guard)</span>
          <div><span class="status-badge {traffic_badge_cls}">{traffic_badge_txt}</span></div>
        </div>
        <div class="summary-banner-item">
          <span class="muted">ปัญหาที่พบล่าสุด (Recent Problems)</span>
          <strong style="color: {'var(--critical)' if problem_events else 'var(--ok)'};">{len(problem_events)} รายการ</strong>
        </div>
      </section>

      <section class="website-detail-grid" style="grid-template-columns: minmax(0, 1fr);">
        <div class="mock-panel">
          <div class="clean-tabs-bar" role="tablist">
            <button type="button" class="clean-tab-btn active" data-wtab-target="wtab-diagram" onclick="switchWebsiteTab('wtab-diagram', this)">
              🗺️ 1. แผนผังระบบ (ER Diagram)
            </button>
            <button type="button" class="clean-tab-btn" data-wtab-target="wtab-traffic" onclick="switchWebsiteTab('wtab-traffic', this)">
              🛡️ 2. ทราฟฟิก &amp; ความปลอดภัย ({traffic_badge_txt})
            </button>
            <button type="button" class="clean-tab-btn" data-wtab-target="wtab-problems" onclick="switchWebsiteTab('wtab-problems', this)">
              📋 3. ปัญหาที่พบล่าสุด ({len(problem_events)})
            </button>
            <button type="button" class="clean-tab-btn" id="tab-btn-ai" data-wtab-target="wtab-ai" onclick="openAiTabAndAnalyze('{_h(selected_website_id)}')">
              🤖 4. วิเคราะห์ด้วย AI (AI Insight อัตโนมัติ)
            </button>
            <span hidden>Run AI Diagnostics</span>
          </div>

          <!-- TAB 1: Visual System & Cluster Diagram -->
          <div id="wtab-diagram" class="wtab-pane active">
            {_render_er_topology_section(selected_website_id, agents, er_topology, topology_hints, source_counts)}
          </div>

          <!-- TAB 2: Traffic & Security Guard -->
          <div id="wtab-traffic" class="wtab-pane" hidden>
            {_render_traffic_guard_section(selected_website_id, traffic_summary)}
          </div>

          <!-- TAB 3: Recent Problems & Server Fleet -->
          <div id="wtab-problems" class="wtab-pane" hidden>
            <div class="detail-head" style="margin-bottom: 10px;">
              <h2>ปัญหาที่พบล่าสุด (Recent Problems)</h2>
              <a class="secondary" href="{_h(_dashboard_href('logs', selected_website_id))}" style="text-decoration:none; padding:6px 10px; border-radius:6px; border:1px solid var(--border); font-size:13px;">ดูประวัติ Log ทั้งหมด</a>
            </div>
            <div style="max-height: 440px; overflow-y: auto; border: 1px solid var(--border); border-radius: var(--radius);">
              <table style="border: 0;">
                <thead style="position: sticky; top: 0; z-index: 5;"><tr><th style="width:185px;">เวลา (Time)</th><th style="width:110px;">เครื่อง (Machine)</th><th style="width:120px;">ระดับ (Severity)</th><th style="width:170px;">หมวดหมู่ (Category)</th><th>รายละเอียด (Message)</th></tr></thead>
                <tbody>{problem_rows or '<tr><td colspan="5">ไม่พบปัญหาในขณะนี้ (No recent problems)</td></tr>'}</tbody>
              </table>
            </div>

            <div hidden style="display:none !important;">
              <h2 style="margin-top: 22px;">สถานะเครื่องรายตัว (Server Fleet Status)</h2>
              <p class="muted" style="margin-bottom: 10px; font-size: 12px;">คลิกที่การ์ดเครื่องเพื่อดูรายการไฟล์ Log ของเครื่องนั้นโดยตรง</p>
              <div class="fleet-mini-grid">{fleet_cards or '<div class="muted">No agents connected</div>'}</div>
            </div>
          </div>

          <!-- TAB 4: Dedicated AI Insight & Diagnostics Page -->
          <div id="wtab-ai" class="wtab-pane" hidden>
            <aside class="ai-dedicated-page ai-side-panel">
              <div class="detail-head" style="margin-bottom: 14px;">
                <div>
                  <h2 style="margin-bottom: 2px;">🤖 วิเคราะห์สาเหตุและผลกระทบด้วย AI</h2>
                </div>
                <div style="display: flex; gap: 8px;">
                  <button class="ai-btn" type="button" onclick="runAiAnalysis('{_h(selected_website_id)}')">🔄 สั่งวิเคราะห์ใหม่</button>
                </div>
              </div>
              <div class="ai-summary-cards-row">
                <div class="ai-box">
                  <h3>🎯 เครื่องต้นตอ <span hidden>Suspected Machine</span></h3>
                  <p><strong id="ai-card-suspected" style="color: var(--critical); font-size: 24px;">{_h(suspected)}</strong></p>
                </div>
                <div class="ai-box">
                  <h3>⚡ ปัญหาที่พบ <span hidden>Primary Signal</span></h3>
                  <p><strong id="ai-card-signal">{_h(insight['primary_signal_th'])}</strong><span hidden>{_h(insight['primary_signal'])}</span></p>
                </div>
                <div class="ai-box">
                  <h3>💡 สาเหตุ <span hidden>Root cause</span></h3>
                  <p><strong id="ai-card-cause">{_h(insight['root_cause_th'])}</strong><span hidden>{_h(insight['root_cause'])}</span></p>
                </div>
                <div class="ai-box">
                  <h3>🛠️ วิธีแก้ไข <span hidden>Action</span></h3>
                  <p><strong id="ai-card-action">{_h(insight['action_th'])}</strong><span hidden>{_h(insight['action'])}</span></p>
                </div>
              </div>
              <div id="ai-panel-content" class="ai-inline-report" style="margin-top: 16px;"></div>
            </aside>
          </div>
        </div>
      </section>""".rstrip()


def _render_node_vitals_bars(node: dict[str, Any]) -> str:
    cpu = node.get("cpu_percent")
    ram = node.get("ram_percent")
    disk = node.get("disk_percent")
    if cpu is None and ram is None and disk is None:
        return ""
    bars: list[str] = []
    if cpu is not None:
        c_val = max(0.0, min(100.0, float(cpu)))
        bars.append(
            f'<div class="vital-row"><span>CPU {c_val:.0f}%</span>'
            f'<div class="vital-track"><div class="vital-fill" style="width: {c_val:.0f}%;"></div></div></div>'
        )
    if ram is not None:
        r_val = max(0.0, min(100.0, float(ram)))
        bars.append(
            f'<div class="vital-row"><span>RAM {r_val:.0f}%</span>'
            f'<div class="vital-track"><div class="vital-fill" style="width: {r_val:.0f}%;"></div></div></div>'
        )
    if disk is not None:
        d_val = max(0.0, min(100.0, float(disk)))
        bars.append(
            f'<div class="vital-row"><span>Disk {d_val:.0f}%</span>'
            f'<div class="vital-track"><div class="vital-fill" style="width: {d_val:.0f}%;"></div></div></div>'
        )
    return f'<div class="node-vitals">{"".join(bars)}</div>'


def _quorum_badge_html(quorum_status: str, healthy_nodes: int, total_nodes: int) -> str:
    normalized = str(quorum_status or "").lower()
    if normalized == "healthy":
        return f'<span class="status-badge status-ok">🟢 สถานะปกติ {healthy_nodes}/{total_nodes} เครื่อง (Healthy)</span>'
    if normalized == "degraded":
        return f'<span class="status-badge status-warning">🟡 ทำงานทดแทนกัน {healthy_nodes}/{total_nodes} เครื่อง (Failover)</span>'
    if normalized == "quorum_lost":
        return f'<span class="status-badge status-critical">🔴 คลัสเตอร์ล่ม {healthy_nodes}/{total_nodes} เครื่อง (Quorum Lost)</span>'
    return f'<span class="status-badge status-nodata">⚪ รอข้อมูล ({healthy_nodes}/{total_nodes})</span>'


def _relation_thai_label(rtype: str) -> str:
    rt = rtype.upper()
    if rt == "PEER_SYNC":
        return "ซิงค์ข้อมูลคลัสเตอร์ (PEER_SYNC)"
    if rt == "ROUTE_TO":
        return "ส่งต่อทราฟฟิก/เชื่อมต่อ (ROUTE_TO)"
    if rt == "REPLICATE":
        return "สำรองฐานข้อมูล (REPLICATE)"
    if rt == "MOUNT":
        return "เชื่อมต่อดิสก์กลาง (MOUNT)"
    return rt


def _render_er_topology_section(
    website_id: str,
    agents: list[dict[str, Any]],
    er_topology: dict[str, Any] | None,
    topology_hints: list[dict[str, Any]],
    source_counts: dict[str, int] | None = None,
) -> str:
    import json as _json
    source_counts = source_counts or {}
    graph = er_topology or {}
    clusters = list(graph.get("clusters") or [])
    nodes = list(graph.get("nodes") or agents)
    relations = list(graph.get("relations") or [])
    node_by_id = {str(n.get("agent_id") or ""): n for n in nodes if n.get("agent_id")}

    zone_boxes_html: list[str] = []
    entity_tables_html: list[str] = []
    clustered_ids: set[str] = set()

    # 1. Position unclustered / upstream VMs in top zone (warm beige like Moon Modeler)
    unclustered: list[dict[str, Any]] = []
    for cluster in clusters:
        for mid in (cluster.get("member_ids") or []):
            clustered_ids.add(str(mid))
    for n in nodes:
        if str(n.get("agent_id") or "") not in clustered_ids:
            unclustered.append(n)

    if unclustered:
        u_ids = [str(n.get("agent_id") or "") for n in unclustered if n.get("agent_id")]
        zone_boxes_html.append(
            f'<div class="er-zone-box er-zone-beige er-cluster-card" id="er-zone-upstream_gateway" '
            f'data-cluster-id="cluster:upstream_gateway" data-cluster-name="tier: upstream_gateway" '
            f'data-zone-members="{_h(",".join(u_ids))}" style="left: 26px; top: 20px; width: 420px; height: 236px;">'
            f'<span class="er-zone-anchor er-zone-anchor-top" data-zone-connect="cluster:upstream_gateway" title="ลากเพื่อเชื่อมระดับคลัสเตอร์"></span>'
            f'<span class="er-zone-anchor er-zone-anchor-bottom" data-zone-connect="cluster:upstream_gateway" title="ลากเพื่อเชื่อมระดับคลัสเตอร์"></span>'
            f'<span class="er-zone-anchor er-zone-anchor-left" data-zone-connect="cluster:upstream_gateway" title="ลากเพื่อเชื่อมระดับคลัสเตอร์"></span>'
            f'<span class="er-zone-anchor er-zone-anchor-right" data-zone-connect="cluster:upstream_gateway" title="ลากเพื่อเชื่อมระดับคลัสเตอร์"></span>'
            f'<div class="er-zone-header" data-er-drag-handle="er-zone-upstream_gateway">'
            f'<strong class="er-zone-title-text">tier: upstream_gateway (กลุ่มเครื่องต้นทาง)</strong>'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'<span class="status-badge status-ok">{len(u_ids)} เครื่อง</span>'
            f'<button type="button" class="er-dots-btn" onclick="openErEditModal(\'cluster\', \'upstream_gateway\')" title="ตั้งค่าคลัสเตอร์">⋯</button>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
        for idx, node in enumerate(unclustered):
            mid = str(node.get("agent_id") or "")
            left_px = 48 + (idx * 310)
            top_px = 76
            entity_tables_html.append(
                _render_er_entity_table(website_id, mid, node, source_counts.get(mid, 0), left_px, top_px, is_peer=False)
            )

    # 2. Position each Cluster Zone (soft blue / green zones) and its member VM tables
    base_top = 345 if unclustered else 76
    zone_palettes = ["er-zone-blue", "er-zone-green", "er-zone-beige"]
    for c_idx, cluster in enumerate(clusters):
        cid = str(cluster.get("cluster_id") or "")
        cname = str(cluster.get("name") or cid)
        ctype = str(cluster.get("cluster_type") or "ha_cluster")
        q_status = str(cluster.get("quorum_status") or "healthy")
        healthy_n = int(cluster.get("healthy_nodes") or 0)
        total_n = int(cluster.get("total_nodes") or 0)
        member_ids = [str(m) for m in (cluster.get("member_ids") or [])]
        palette_cls = zone_palettes[c_idx % len(zone_palettes)]
        row_top = base_top + (c_idx * 275)
        init_zone_top = max(14, row_top - 56)
        init_zone_w = max(420, len(member_ids) * 320 + 60)
        empty_hint = (
            '<div class="er-empty-cluster-hint">ลากเครื่อง VM มาวางในกรอบนี้ หรือกดปุ่ม <b>⋯</b> มุมขวาบนเพื่อตั้งชื่อ/เลือกเครื่อง</div>'
            if not member_ids
            else ""
        )
        zone_boxes_html.append(
            f'<div class="er-zone-box {palette_cls} er-cluster-card" id="er-zone-{_h(cid)}" '
            f'data-cluster-id="{_h(cid)}" data-cluster-name="{_h(cname)}" data-cluster-type="{_h(ctype)}" '
            f'data-zone-members="{_h(",".join(member_ids))}" '
            f'style="left: 34px; top: {init_zone_top}px; width: {init_zone_w}px; height: 236px;">'
            f'<span class="er-zone-anchor er-zone-anchor-top" data-zone-connect="cluster:{_h(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>'
            f'<span class="er-zone-anchor er-zone-anchor-bottom" data-zone-connect="cluster:{_h(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>'
            f'<span class="er-zone-anchor er-zone-anchor-left" data-zone-connect="cluster:{_h(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>'
            f'<span class="er-zone-anchor er-zone-anchor-right" data-zone-connect="cluster:{_h(cid)}" title="ลากเพื่อเชื่อมทั้งคลัสเตอร์"></span>'
            f'<div class="er-zone-header" data-er-drag-handle="er-zone-{_h(cid)}">'
            f'<strong class="er-zone-title-text">cluster: {_h(cname)}</strong>'
            f'<div style="display:flex;align-items:center;gap:6px;">'
            f'{_quorum_badge_html(q_status, healthy_n, total_n)}'
            f'<button type="button" class="er-dots-btn" onclick="openErEditModal(\'cluster\', \'{_h(cid)}\')" title="แก้ไขคลัสเตอร์">⋯</button>'
            f'</div>'
            f'</div>'
            f'{empty_hint}'
            f'<div class="er-zone-resize-handle" title="ลากมุมนี้เพื่อปรับขนาดคลัสเตอร์"></div>'
            f'</div>'
        )
        for m_idx, mid in enumerate(member_ids):
            node = node_by_id.get(mid, {"agent_id": mid, "agent_role": "db", "is_healthy": True})
            left_px = 42 + (m_idx * 270)
            top_px = row_top + (12 if m_idx % 2 == 1 else 0)
            entity_tables_html.append(
                _render_er_entity_table(
                    website_id,
                    mid,
                    node,
                    source_counts.get(mid, 0),
                    left_px,
                    top_px,
                    is_peer=(m_idx > 0),
                )
            )

    total_clusters_rows = max(1, len(clusters) + (1 if unclustered else 0))
    canvas_height = max(560, total_clusters_rows * 255 + 60)

    js_relations = []
    relation_lines: list[str] = []
    for rel in relations:
        rel_id = str(rel.get("relation_id") or "")
        src = str(rel.get("source_id") or "")
        dst = str(rel.get("target_id") or "")
        rtype = str(rel.get("relation_type") or "ROUTE_TO").upper()
        thai_rel = _relation_thai_label(rtype)
        port_sfx = f":{rel['port']}" if rel.get("port") else ""
        js_relations.append({
            "relation_id": rel_id,
            "source_id": src,
            "target_id": dst,
            "relation_type": rtype,
            "port": rel.get("port"),
            "label": f"{rtype}{port_sfx}",
        })
        arrow_txt = "◀─── " + _h(thai_rel) + " ───▶" if rtype == "PEER_SYNC" else "─── " + _h(thai_rel) + " ───▶"
        del_btn = (
            f'<button type="button" class="close-btn-sm" data-delete-relation="{_h(rel_id)}">ลบเส้นเชื่อม</button>'
            if rel.get("is_manual") and rel_id
            else '<span class="auto-chip">ตรวจพบอัตโนมัติ</span>'
        )
        relation_lines.append(
            f'<div class="er-relation-line">'
            f'<span class="agent-pill">🖥️ {_h(src)}</span>'
            f'<span class="er-edge-label">{arrow_txt}</span>'
            f'<span class="agent-pill">🗄️ {_h(dst)}{_h(port_sfx)}</span>'
            f'{del_btn}'
            f'</div>'
        )

    relations_json_attr = _h(_json.dumps(js_relations))
    relations_block = (
        "".join(relation_lines)
        if relation_lines
        else '<div class="muted">ยังไม่มีเส้นเชื่อมความสัมพันธ์ระหว่างเครื่อง</div>'
    )

    er_payload = {
        "websiteId": website_id,
        "clusters": [
            {
                "clusterId": str(c.get("cluster_id") or c.get("id") or ""),
                "name": str(c.get("name") or c.get("cluster_id") or ""),
                "quorumStatus": str(c.get("quorum_status") or "nodata"),
                "healthyNodes": int(c.get("healthy_nodes") or 0),
                "totalNodes": int(c.get("total_nodes") or 0),
                "memberIds": [str(m) for m in (c.get("member_ids") or [])],
            }
            for c in clusters
        ],
        "agents": [
            {
                "agentId": str(n.get("agent_id") or ""),
                "role": str(n.get("agent_role") or "app"),
                "hostname": str(n.get("hostname") or n.get("agent_id") or ""),
                "isHealthy": bool(n.get("is_healthy", True)),
                "sourceCount": int(source_counts.get(str(n.get("agent_id") or ""), 0)),
            }
            for n in nodes
        ],
        "relations": js_relations,
    }
    er_payload_attr = _h(_json.dumps(er_payload, ensure_ascii=False))

    return f"""
          <div class="er-topology-section">
            <div class="detail-head" style="margin-bottom: 10px; flex-wrap: wrap;">
              <div>
                <h2>แผนผัง ER Diagram โครงสร้างเซิร์ฟเวอร์ &amp; คลัสเตอร์</h2>
              </div>
              <div style="display: flex; gap: 8px; flex-wrap: wrap; align-items: center;">
                <button type="button" class="secondary" onclick="toggleErPaletteDrawer()" style="font-size: 13px; padding: 5px 10px;">◀ เปิด/ปิด แถบอุปกรณ์</button>
                <button type="button" class="secondary" onclick="resetErCanvasLayout()" style="font-size: 13px; padding: 5px 10px;">🔄 จัดเรียงอัตโนมัติ</button>
              </div>
            </div>

            <div class="er-workspace-wrapper">
              <div id="er-interactive-canvas" class="er-diagram-canvas" style="height: 640px;" data-website-id="{_h(website_id)}" data-er-relations="{relations_json_attr}">
                <div id="er-xyflow-root" style="width:100%; height:100%;" data-er-payload="{er_payload_attr}"></div>
              </div>

              <!-- Side Palette Drawer with Arrow Toggle (Only 2 Items: Cluster & VM) -->
              <aside id="er-palette-drawer" class="er-palette-drawer">
                <button type="button" id="er-palette-arrow" class="er-palette-arrow-btn" onclick="toggleErPaletteDrawer()" title="พับ/กาง แถบอุปกรณ์">▶</button>
                <div class="er-palette-body">
                  <h3>🧰 อุปกรณ์</h3>
                  <div class="er-palette-list">
                    <div class="er-palette-item" draggable="true" data-palette-type="cluster" data-palette-role="ha_cluster">
                      <span class="er-palette-icon" style="background:#16a34a;">📦</span>
                      <div><strong>กลุ่มคลัสเตอร์ (Cluster)</strong></div>
                    </div>
                    <div class="er-palette-item" draggable="true" data-palette-type="vm" data-palette-role="vm">
                      <span class="er-palette-icon" style="background:#0288d1;">🖥️</span>
                      <div><strong>เครื่องเซิร์ฟเวอร์ (VM)</strong></div>
                    </div>
                  </div>
                </div>
              </aside>
            </div>

            <!-- Inline Edit Modal for Cluster & VM -->
            <div id="er-edit-modal" class="modal-overlay" style="display: none;">
              <div class="modal-card" style="max-width: 440px;">
                <div class="modal-header">
                  <h3 id="er-edit-modal-title">✏️ แก้ไขข้อมูลบนแผนผัง ER</h3>
                  <button type="button" class="close-btn" onclick="closeErEditModal()">&times;</button>
                </div>
                <div class="modal-body" id="er-edit-modal-body"></div>
              </div>
            </div>

            <form id="create-cluster" hidden>
              <input type="hidden" name="website_id" value="{_h(website_id)}">
              <input name="name" value="">
              <input name="cluster_type" value="galera_cluster">
              <input name="quorum_min" value="2">
            </form>
            <form id="create-relation" hidden>
              <input type="hidden" name="website_id" value="{_h(website_id)}">
              <input name="source_id" value="">
              <input name="target_id" value="">
              <input name="relation_type" value="ROUTE_TO">
            </form>
          </div>""".rstrip()


def _render_er_entity_table(
    website_id: str,
    agent_id: str,
    node: dict[str, Any],
    source_count: int,
    left_px: int,
    top_px: int,
    is_peer: bool = False,
) -> str:
    is_healthy = bool(node.get("is_healthy", str(node.get("status") or "").lower() in {"active", "online"}))
    in_maint = bool(node.get("in_maintenance") or node.get("maintenance_until"))
    if not is_healthy:
        hdr_cls = "er-hdr-red"
    elif is_peer:
        hdr_cls = "er-hdr-purple"
    else:
        hdr_cls = "er-hdr-blue"

    role_lbl = str(node.get("agent_role") or "node")
    hostname = str(node.get("hostname") or agent_id)
    if len(hostname) > 20:
        hostname = hostname[:18] + ".."

    status_txt = "MAINT" if in_maint else ("ONLINE" if is_healthy else "OFFLINE")
    status_color = "#d97706" if in_maint else ("#16a34a" if is_healthy else "#dc2626")

    cpu = node.get("cpu_percent")
    ram = node.get("ram_percent")
    vitals_txt = (
        f"cpu {float(cpu):.0f}% · ram {float(ram):.0f}%"
        if (cpu is not None and ram is not None)
        else f"{source_count} log files"
    )
    title_suffix = " {} NN" if is_peer else ""
    maint_btn = (
        f'<button type="button" class="maint-btn-sm" data-maintenance-agent="{_h(agent_id)}" '
        f'data-maintenance-minutes="{0 if in_maint else 60}">'
        f'{"ยกเลิกซ่อม" if in_maint else "ซ่อมบำรุง"}</button>'
    )

    return (
        f'<div class="er-entity-table er-member-node" id="er-node-{_h(agent_id)}" '
        f'data-agent-id="{_h(agent_id)}" data-agent-host="{_h(str(node.get("hostname") or agent_id))}" '
        f'data-agent-role="{_h(role_lbl)}" data-cluster-id="{_h(str(node.get("cluster_id") or ""))}" '
        f'data-init-left="{left_px}" data-init-top="{top_px}" '
        f'style="left: {left_px}px; top: {top_px}px;">'
        f'<div class="er-entity-header {hdr_cls}" data-er-drag-handle="er-node-{_h(agent_id)}">'
        f'<span class="er-vm-title-text">{_h(agent_id)}{title_suffix}</span>'
        f'<button type="button" class="er-hdr-dots" onclick="openErEditModal(\'vm\', \'{_h(agent_id)}\')" title="แก้ไข/ลบ VM">⋯</button>'
        f'</div>'
        f'<div class="er-entity-rows">'
        f'<div class="er-entity-row" id="er-port-in-{_h(agent_id)}">'
        f'<span class="er-anchor-dot er-anchor-left"></span>'
        f'<span class="er-col-name">🔑 _host</span>'
        f'<span class="er-col-type er-vm-host-text">{_h(hostname)} NN</span>'
        f'</div>'
        f'<div class="er-entity-row">'
        f'<span class="er-col-name">⚡ status</span>'
        f'<span class="er-col-type" style="color: {status_color}; font-weight: 700;">{status_txt}</span>'
        f'</div>'
        f'<div class="er-entity-row">'
        f'<span class="er-col-name">📊 metrics</span>'
        f'<span class="er-col-type">{_h(vitals_txt)}</span>'
        f'</div>'
        f'<div class="er-entity-row" id="er-port-out-{_h(agent_id)}">'
        f'<span class="er-anchor-dot er-anchor-left"></span>'
        f'<span class="er-col-name">🔌 <span class="er-vm-role-text">{_h(role_lbl)}</span> <b style="color:#d97706;">{{}}</b></span>'
        f'<span class="er-col-type">link 👁</span>'
        f'<span class="er-anchor-dot er-anchor-right"></span>'
        f'</div>'
        f'<div class="er-entity-footer">'
        f'<a class="node-link-sm" href="{_h(_agent_detail_href(website_id, agent_id))}">ดู Log →</a>'
        f'</div>'
        f'</div>'
        f'</div>'
    )


def _render_traffic_guard_section(
    website_id: str,
    traffic_summary: dict[str, Any] | None,
) -> str:
    summary = traffic_summary or {}
    req_1m = int(summary.get("requests_1m") or 0)
    req_5m = int(summary.get("requests_5m") or 0)
    baseline = float(summary.get("rpm_baseline") or 0.0)
    status_counts = dict(summary.get("status_counts") or {})
    s2xx = int(status_counts.get("2xx") or 0)
    s4xx = int(status_counts.get("4xx") or 0)
    s5xx = int(status_counts.get("5xx") or 0)
    err_rate = float(summary.get("error_rate_percent") or 0.0)
    top_ips = list(summary.get("top_ips") or [])
    anomalies = list(summary.get("recent_anomalies") or [])

    ip_pills = (
        ", ".join(f"{_h(item.get('ip'))} ({int(item.get('count') or 0)} ครั้ง)" for item in top_ips)
        if top_ips
        else "ยังไม่มี IP ผิดปกติ"
    )
    anomaly_rows: list[str] = []
    for item in anomalies[:5]:
        atype = str(item.get("anomaly_type") or "anomaly")
        asev = str(item.get("severity") or "warning")
        atitle = str(item.get("title") or atype)
        adesc = str(item.get("description") or "")
        anomaly_rows.append(
            f'<div class="traffic-anomaly-card">'
            f'<div><span class="status-badge {_severity_badge_class(asev)}">{_h(atype)}</span> '
            f'<strong>{_h(atitle)}</strong></div>'
            f'<div class="muted">{_h(adesc)}</div>'
            f'</div>'
        )
    anomaly_html = (
        "".join(anomaly_rows)
        if anomaly_rows
        else '<div class="traffic-ok-banner">🟢 ทราฟฟิกปกติ — ไม่พบการโจมตี DDoS (traffic_spike), เว็บเงียบผิดปกติ (traffic_drop), สแกนรหัสผ่าน (brute_force) หรือ 5xx พุ่งสูง (error_burst)</div>'
    )

    return f"""
          <div class="traffic-guard-section">
            <div class="detail-head" style="margin-bottom: 12px;">
              <div>
                <h2>🛡️ ระบบตรวจจับทราฟฟิก &amp; ความปลอดภัย (Traffic Guard)</h2>
                <span class="muted" style="font-size: 12px;">ตรวจจับ DDoS/Flood, เว็บเงียบผิดปกติ, สแกนพอร์ต/รหัสผ่าน และ HTTP 5xx พุ่งสูงอัตโนมัติ</span>
              </div>
            </div>
            <div class="traffic-metrics-grid">
              <div class="traffic-metric-box">
                <span class="muted">ปริมาณคำขอ (1 นาที / 5 นาที)</span>
                <strong>{req_1m} / {req_5m} req</strong>
                <span class="muted">ค่าเฉลี่ยปกติ (Baseline): {baseline:.1f} rpm</span>
              </div>
              <div class="traffic-metric-box">
                <span class="muted">สัดส่วนรหัสตอบกลับ (HTTP Status)</span>
                <strong>ปกติ 2xx: {s2xx} · ปฏิเสธ 4xx: {s4xx} · พัง 5xx: {s5xx}</strong>
              </div>
              <div class="traffic-metric-box">
                <span class="muted">อัตราเกิดข้อผิดพลาด (Error Rate %)</span>
                <strong style="color: {'var(--critical)' if err_rate >= 15.0 else 'var(--ok)'};">{err_rate:.1f}%</strong>
                <span class="muted">เกณฑ์แจ้งเตือน: ≥ 15.0%</span>
              </div>
              <div class="traffic-metric-box">
                <span class="muted">IP ที่ยิงคำขอสูงสุด (Top Client IPs)</span>
                <strong>{ip_pills}</strong>
              </div>
            </div>
            <div class="traffic-anomaly-list" style="margin-top: 14px;">
              <h3>รายการแจ้งเตือนความผิดปกติของทราฟฟิก</h3>
              {anomaly_html}
            </div>
          </div>""".rstrip()


def _render_agent_detail(
    website_id: str,
    agent: dict[str, Any],
    sources: list[dict[str, Any]],
    events: list[dict[str, Any]],
) -> str:
    agent_id = str(agent.get("agent_id") or "")
    problem_events = [event for event in events if event.get("severity") in {"warning", "problem", "critical"}]
    source_rows = "\n".join(
        f"<tr><td><a class='table-link' href='{_h(_source_detail_href(website_id, agent_id, str(source['source_id'])))}'>"
        f"<strong>{_h(source['name'])}</strong></a></td>"
        f"<td><span class='source-type'>{_h(source['classification'])}</span></td>"
        f"<td><span class='status-badge {_source_status_class(str(source['status']))}'>{_h(source['status'])}</span></td>"
        f"<td class='source-path' title='{_h(source['path'])}'>{_h(source['path'])}</td></tr>"
        for source in sources
    )
    problem_rows = "\n".join(
        f"<tr><td class='log-time'>{_h(event['timestamp'])}</td>"
        f"<td><span class='status-badge {_severity_badge_class(str(event['severity']))}'>{_h(event['severity'])}</span></td>"
        f"<td>{_h(event['category'])}</td><td class='log-message'>{_render_log_message(event['message'])}</td></tr>"
        for event in problem_events[:10]
    )
    status = str(agent.get("health_status") or agent.get("status") or "unknown")
    is_online = status.lower() in {"active", "online", "healthy"}
    badge_cls = "status-ok" if is_online else "status-critical"
    badge_txt = "ONLINE" if is_online else status.upper()
    return f"""
      <div class="detail-column">
        <nav class="detail-breadcrumb"><a href="{_h(_dashboard_href('website', website_id))}">{_h(website_id)}</a><span>/</span><strong>{_h(agent_id)}</strong></nav>
        <section class="mock-panel agent-detail-summary">
          <div class="detail-head"><div><h2>{_h(agent_id)}</h2><div class="muted">{_h(agent.get('hostname') or agent_id)}</div></div>
          <span class="status-badge {badge_cls}">{_h(badge_txt)}</span></div>
          <dl class="fleet-facts agent-facts" style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-top:12px;">
            <div style="display:block;padding:10px 14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"><dt class="muted" style="font-size:12px;">บทบาท (Role)</dt><dd style="margin:4px 0 0;font-size:15px;font-weight:700;">{_h(agent.get('agent_role') or '-')}</dd></div>
            <div style="display:block;padding:10px 14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"><dt class="muted" style="font-size:12px;">ไฟล์ Log ที่ตรวจพบ (Log sources)</dt><dd style="margin:4px 0 0;font-size:15px;font-weight:700;">{len(sources)} ไฟล์</dd></div>
            <div style="display:block;padding:10px 14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"><dt class="muted" style="font-size:12px;">ปัญหาที่พบ (Problems)</dt><dd style="margin:4px 0 0;font-size:15px;font-weight:700;color:{'var(--critical)' if problem_events else 'var(--ok)'};">{len(problem_events)} รายการ</dd></div>
            <div style="display:block;padding:10px 14px;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;"><dt class="muted" style="font-size:12px;">อัปเดตล่าสุด (Last seen)</dt><dd style="margin:4px 0 0;font-size:13px;font-weight:600;">{_h(agent.get('last_seen_at') or '-')}</dd></div>
          </dl>
        </section>
        <section class="mock-panel">
          <h2>Log Sources (รายการไฟล์ Log ที่ Agent ตรวจพบอัตโนมัติบนเครื่องนี้)</h2>
          <table class="source-table">
            <thead><tr><th>Source</th><th>Class</th><th>Status</th><th>Path</th></tr></thead>
            <tbody>{source_rows or '<tr><td colspan="4">No log sources selected for this machine</td></tr>'}</tbody>
          </table>
        </section>
        <section class="mock-panel">
          <h2>Recent Problems (ปัญหาล่าสุดของเครื่องนี้)</h2>
          <table><thead><tr><th>Time</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead>
            <tbody>{problem_rows or '<tr><td colspan="4">No recent problems on this machine</td></tr>'}</tbody>
          </table>
        </section>
      </div>""".rstrip()


def _render_source_detail(
    website_id: str,
    agent: dict[str, Any],
    source: dict[str, Any],
    events: list[dict[str, Any]],
    log_page: int,
    total_log_events: int,
    raw_source_logs: list[dict[str, Any]] | None = None,
) -> str:
    agent_id = str(agent.get("agent_id") or "")
    rows = "\n".join(
        f"<tr><td class='log-time'>{_h(event['timestamp'])}</td>"
        f"<td><span class='status-badge {_severity_badge_class(str(event['severity']))}'>{_h(event['severity'])}</span></td>"
        f"<td>{_h(event['category'])}</td><td class='log-message'>{_render_log_message(event['message'])}</td></tr>"
        for event in events
    )
    combined_raw: list[dict[str, Any]] = []
    seen_sigs: set[tuple[str, str]] = set()
    for item in (raw_source_logs or []):
        sig = (str(item.get("timestamp") or ""), str(item.get("message") or ""))
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            combined_raw.append(item)
    for event in events:
        meta = dict(event.get("metadata") or {})
        for ctx in (meta.get("context_before") or []):
            sig = (str(ctx.get("timestamp") or ""), str(ctx.get("message") or ""))
            if sig not in seen_sigs:
                seen_sigs.add(sig)
                combined_raw.append(
                    {
                        "timestamp": ctx.get("timestamp") or "-",
                        "severity": ctx.get("severity") or "normal",
                        "category": ctx.get("category") or "normal",
                        "message": ctx.get("message") or "",
                    }
                )
        sig = (str(event.get("timestamp") or ""), str(event.get("message") or ""))
        if sig not in seen_sigs:
            seen_sigs.add(sig)
            combined_raw.append(event)
    combined_raw.sort(key=lambda x: str(x.get("timestamp") or ""), reverse=True)
    raw_rows = "\n".join(
        f"<tr class='raw-log-row' data-log-ts='{_h(item.get('timestamp') or '')}'>"
        f"<td class='log-time'>{_h(item.get('timestamp') or '-')}</td>"
        f"<td><span class='status-badge {_severity_badge_class(str(item.get('severity') or 'normal'))}'>{_h(item.get('severity') or 'normal')}</span></td>"
        f"<td class='log-message'>{_render_log_message(str(item.get('message') or ''))}</td></tr>"
        for item in combined_raw[:100]
    )
    return f"""
      <div class="detail-column">
        <nav class="detail-breadcrumb"><a href="{_h(_dashboard_href('website', website_id))}">{_h(website_id)}</a><span>/</span>
          <a href="{_h(_agent_detail_href(website_id, agent_id))}">{_h(agent_id)}</a><span>/</span><strong>{_h(source['name'])}</strong></nav>
        <section class="mock-panel source-detail-head">
          <div><h2>{_h(source['name'])}</h2><div class="source-path">{_h(source['path'])}</div></div>
          <span class="status-badge {_source_status_class(str(source['status']))}">{_h(source['status'])}</span>
        </section>
        <section class="mock-panel">
          <div class="detail-head" style="margin-bottom: 10px; flex-wrap: wrap; gap: 10px;">
            <h2>Log</h2>
            <div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">
              <label style="font-size: 12px; display: flex; align-items: center; gap: 4px; margin: 0;">
                แสดง:
                <select id="raw-log-limit" onchange="filterSourceRawLogs()" style="padding: 4px 8px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;">
                  <option value="10">10 บรรทัดล่าสุด</option>
                  <option value="50">50 บรรทัดล่าสุด</option>
                  <option value="100" selected>100 บรรทัดล่าสุด</option>
                </select>
              </label>
              <label style="font-size: 12px; display: flex; align-items: center; gap: 4px; margin: 0;">
                ตั้งแต่เวลา:
                <input type="datetime-local" id="raw-log-from" onchange="filterSourceRawLogs()" style="padding: 3px 6px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;">
              </label>
              <label style="font-size: 12px; display: flex; align-items: center; gap: 4px; margin: 0;">
                ถึงเวลา:
                <input type="datetime-local" id="raw-log-to" onchange="filterSourceRawLogs()" style="padding: 3px 6px; border: 1px solid var(--border); border-radius: 6px; font-size: 12px;">
              </label>
              <button type="button" class="secondary" onclick="location.reload()" style="font-size:12px;padding:4px 10px;">↻ รีเฟรช</button>
            </div>
          </div>
          <div style="max-height: 280px; overflow-y: auto; border: 1px solid var(--border); border-radius: 8px;">
            <table id="raw-log-table"><thead><tr><th>Time</th><th>Severity</th><th>Message</th></tr></thead>
              <tbody>{raw_rows or '<tr><td colspan="3">No log lines available</td></tr>'}</tbody>
            </table>
          </div>
        </section>
        <section class="log-panel" id="log-panel">
          <h2>Log Stream</h2>
          <table><thead><tr><th>Time</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead>
            <tbody>{rows or '<tr><td colspan="4">No log events from this source</td></tr>'}</tbody>
          </table>
          {_render_source_pagination(website_id, agent_id, str(source['source_id']), log_page, total_log_events)}
        </section>
      </div>""".rstrip()


def _render_source_pagination(
    website_id: str,
    agent_id: str,
    source_id: str,
    current_page: int,
    total_events: int,
) -> str:
    total_pages = max(1, (total_events + LOG_PAGE_SIZE - 1) // LOG_PAGE_SIZE)
    if total_pages <= 1:
        return ""
    links = []
    for page_number in _compact_page_numbers(current_page, total_pages):
        if page_number is None:
            links.append('<span class="page-ellipsis">...</span>')
            continue
        href = f"{_source_detail_href(website_id, agent_id, source_id)}&log_page={page_number}#log-panel"
        links.append(
            f'<a class="page-btn{" active" if page_number == current_page else ""}" href="{_h(href)}">{page_number}</a>'
        )
    return f'<nav class="log-pagination" aria-label="Log pages">{"".join(links)}</nav>'


def _render_topology_hints(topology_hints: list[dict[str, Any]]) -> str:
    rows = "\n".join(
        f"<tr><td><strong>{_h(hint['agent_id'])}</strong></td>"
        f"<td>{_h(hint['hint_type'])}</td>"
        f"<td>{_h(hint['target'])}</td>"
        f"<td>{int(float(hint.get('confidence') or 0) * 100)}%</td>"
        f"<td class='source-path' title='{_h(hint['source'])}'>{_h(hint['source'])}</td></tr>"
        for hint in topology_hints
    )
    return f"""
          <h2 style="margin-top: 18px;">Topology Hints</h2>
          <table class="source-table">
            <thead><tr><th>Machine</th><th>Relation</th><th>Target</th><th>Score</th><th>Source</th></tr></thead>
            <tbody>{rows or '<tr><td colspan="5">No topology hints reported yet</td></tr>'}</tbody>
          </table>""".rstrip()


def _thai_signal_label(sig: str) -> str:
    low = str(sig or "").lower()
    mapping = {
        "connection_refused": "ปฏิเสธการเชื่อมต่อ (connection_refused)",
        "timeout": "การเชื่อมต่อหมดเวลา (timeout)",
        "upstream_timeout": "เซิร์ฟเวอร์ปลายทางตอบสนองช้า (upstream_timeout)",
        "db_too_many_connections": "คิวเชื่อมต่อฐานข้อมูลเต็ม (db_too_many_connections)",
        "disk_full": "พื้นที่ดิสก์เต็ม (disk_full)",
        "out_of_memory": "หน่วยความจำเต็ม (out_of_memory)",
        "permission_denied": "สิทธิ์การเข้าถึงถูกปฏิเสธ (permission_denied)",
        "http_5xx": "ข้อผิดพลาดฝั่งเซิร์ฟเวอร์ (http_5xx)",
        "http_4xx": "คำขอผิดพลาด (http_4xx)",
        "agent_data_loss": "สัญญาณจากเครื่องขาดหายชั่วคราว",
    }
    return mapping.get(low, sig)


def _derive_dashboard_insight(problem_events: list[dict[str, Any]]) -> dict[str, str]:
    if not problem_events:
        return {
            "primary_signal": "No active problem signal",
            "primary_signal_th": "ไม่พบสัญญาณผิดปกติ",
            "root_cause": "No problem evidence found.",
            "root_cause_th": "ทุกระบบทำงานปกติ ไม่พบข้อผิดพลาดในขณะนี้",
            "action": "No action required from current evidence.",
            "action_th": "ไม่ต้องดำเนินการแก้ไข",
        }
    categories: dict[str, int] = {}
    for event in problem_events:
        category = str(event.get("category") or "problem")
        categories[category] = categories.get(category, 0) + 1
    primary_signal = sorted(categories.items(), key=lambda item: (-item[1], item[0]))[0][0]
    sig_th = _thai_signal_label(primary_signal)
    db_events = [event for event in problem_events if event.get("category") == "db_too_many_connections"]
    timeout_events = [
        event
        for event in problem_events
        if event.get("category") in {"upstream_timeout", "timeout", "connection_refused"}
    ]
    if db_events and timeout_events:
        db_agents = ", ".join(sorted({str(event.get("agent_id")) for event in db_events}))
        web_agents = ", ".join(sorted({str(event.get("agent_id")) for event in timeout_events}))
        return {
            "primary_signal": primary_signal,
            "primary_signal_th": sig_th,
            "root_cause": f"DB connection timeout: {db_agents} reported DB pressure and {web_agents} reported timeout.",
            "root_cause_th": f"ฐานข้อมูล {db_agents} มีคิวเชื่อมต่อเต็ม ทำให้เครื่อง {web_agents} เกิดอาการเชื่อมต่อหมดเวลา (Timeout)",
            "action": "Check DB connection limits, slow queries, and app connection pool settings.",
            "action_th": f"ตรวจสอบจำนวน Connection สูงสุดของฐานข้อมูล {db_agents}, คำสั่งคิวรีที่ช้า และการตั้งค่า Connection Pool",
        }
    if db_events:
        db_agents = ", ".join(sorted({str(event.get("agent_id")) for event in db_events}))
        return {
            "primary_signal": primary_signal,
            "primary_signal_th": sig_th,
            "root_cause": f"{db_agents} reported too many connections.",
            "root_cause_th": f"ฐานข้อมูลบนเครื่อง {db_agents} มีจำนวนการเชื่อมต่อเกินขีดจำกัด",
            "action": "Check DB max connections, connection leaks, slow queries, and pool sizing.",
            "action_th": f"ตรวจสอบค่า max_connections บนเครื่อง {db_agents} และตรวจสอบการค้างของ Connection",
        }
    affected_agents = ", ".join(
        sorted({str(event.get("agent_id")) for event in problem_events if event.get("category") == primary_signal})
    )
    return {
        "primary_signal": primary_signal,
        "primary_signal_th": sig_th,
        "root_cause": f"{affected_agents} reported repeated {primary_signal}.",
        "root_cause_th": f"บริการบนเครื่อง {affected_agents} พบปัญหา {sig_th} ซ้ำหลายครั้ง",
        "action": "Review the affected service logs around the same timestamp and compare with upstream/downstream agents in this website.",
        "action_th": f"ตรวจสอบสถานะบริการและพอร์ตเชื่อมต่อบนเครื่อง {affected_agents} ในช่วงเวลาที่เกิดเหตุ",
    }


def _render_fleet_mini_card(
    agent: dict[str, Any],
    events: list[dict[str, Any]],
    website_id: str,
    source_count: int = 0,
) -> str:
    agent_id = str(agent.get("agent_id") or "")
    agent_events = [event for event in events if str(event.get("agent_id")) == agent_id]
    latest = agent_events[0] if agent_events else None
    problem_count = sum(1 for event in agent_events if event.get("severity") in {"warning", "problem", "critical"})
    agent_health = str(agent.get("health_status") or agent.get("status") or "").lower()
    if agent_health in {"stale", "offline", "error"}:
        status, status_class = "Offline", "status-critical"
    else:
        status, status_class = _machine_status(latest, problem_count)
        if latest is None:
            status, status_class = "Active", "status-ok"
    latest_signal = str(latest.get("category") or "No problem signal") if latest else "No problem signal"
    return f"""
      <a class="fleet-mini-card" href="{_h(_agent_detail_href(website_id, agent_id))}">
        <div class="fleet-card-head">
          <strong>{_h(agent_id)}</strong>
          <span class="status-badge {status_class}">{_h(status)}</span>
        </div>
        <dl class="fleet-facts">
          <div><dt>Role</dt><dd>{_h(agent.get('agent_role') or '-')}</dd></div>
          <div><dt>Problems</dt><dd>{problem_count}</dd></div>
          <div><dt>Log sources</dt><dd>{source_count}</dd></div>
          <div><dt>Latest signal</dt><dd>{_h(latest_signal)}</dd></div>
        </dl>
        <div class="muted">Last seen: {_h(agent.get('last_seen_at') or '-')}</div>
      </a>""".rstrip()


def _render_settings_panel(settings: dict[str, Any]) -> str:
    ai = dict(settings.get("ai") or {})
    analysis = dict(settings.get("analysis") or {})
    notifications = dict(settings.get("notifications") or {})
    providers = dict(settings.get("providers") or {})
    api_provider = dict(providers.get("api") or {})
    mode = str(ai.get("mode") or "ollama")
    effective_mode = "api" if mode == "api" else "ollama"
    ollama_provider = dict(providers.get("ollama") or {})
    endpoint_val = str(api_provider.get("endpoint") or ollama_provider.get("url") or "http://127.0.0.1:11434/api/generate")
    min_severity = str(analysis.get("auto_analyze_min_severity") or "critical")
    language = str(notifications.get("language") or "th")
    auto_analyze_checked = " checked" if analysis.get("auto_analyze", True) else ""
    notifications_checked = " checked" if notifications.get("enabled", True) else ""
    health = dict(settings.get("system_health") or {})
    checks = dict(health.get("checks") or {})
    database_health = dict(checks.get("database") or {})
    data_dir_health = dict(checks.get("data_dir") or {})
    agents_health = dict(checks.get("agents") or {})
    incidents_health = dict(checks.get("incidents") or {})
    health_status = str(health.get("status") or "unknown")
    health_label = health_status.title()
    health_class = _severity_badge_class("warning" if health_status == "degraded" else "ok")
    stale_count = int(agents_health.get("stale") or 0)
    total_agents = int(agents_health.get("total") or 0)
    stale_agent_label = f"{stale_count} stale agent{'s' if stale_count != 1 else ''}"
    offline_agent_ids = [str(agent_id) for agent_id in agents_health.get("offline_agent_ids") or []]
    offline_agents = ", ".join(offline_agent_ids) if offline_agent_ids else "None"
    database_status = str(database_health.get("status") or "unknown").upper()
    data_dir_status = "Writable" if data_dir_health.get("writable") else str(data_dir_health.get("status") or "unknown").title()
    return f"""
      <form id="settings-form" class="settings-grid">
        <div class="settings-card">
          <h2>AI Settings</h2>
          <input type="hidden" name="ai.enabled" value="true">
          <label>Mode<select name="ai.mode">
            <option value="ollama"{_selected(effective_mode, "ollama")}>Local</option>
            <option value="api"{_selected(effective_mode, "api")}>API Key</option>
          </select></label>
          <label>Provider<input name="ai.provider" value="{_h(ai.get('provider') or 'ollama')}"></label>
          <label>Model<input name="ai.model" value="{_h(ai.get('model') or 'qwen2.5:3b')}"></label>
          <label>AI API Endpoint<input name="providers.api.endpoint" value="{_h(endpoint_val)}" placeholder="http://127.0.0.1:11434/api/generate หรือ URL ของ API"></label>
          <label>API Key (เฉพาะโหมด API Key)<input name="providers.api.api_key" type="password" value="{_h(api_provider.get('api_key') or '')}" placeholder="เว้นว่างได้หากใช้โหมด Local"></label>
          <input type="hidden" name="providers.api.model" value="{_h(api_provider.get('model') or ai.get('model') or '')}">
        </div>
        <div class="settings-card">
          <h2>Analysis</h2>
          <label><input type="checkbox" name="analysis.auto_analyze"{auto_analyze_checked}> Analyze critical logs immediately</label>
          <label>Minimum Severity<select name="analysis.auto_analyze_min_severity">
            <option value="critical"{_selected(min_severity, "critical")}>Critical</option>
            <option value="problem"{_selected(min_severity, "problem")}>Problem</option>
            <option value="warning"{_selected(min_severity, "warning")}>Warning</option>
          </select></label>
          <label>Analysis Window (minutes)<input name="analysis.time_window_minutes" type="number" min="1" max="1440" value="{_h(analysis.get('time_window_minutes') or 30)}"></label>
          <label>Max Context Events<input name="analysis.max_context_events" type="number" min="1" max="2000" value="{_h(analysis.get('max_context_events') or 100)}"></label>
        </div>
        <div class="settings-card">
          <h2>Notifications</h2>
          <label><input type="checkbox" name="notifications.enabled"{notifications_checked}> Send alerts when triggered</label>
          <label>Language<select name="notifications.language">
            <option value="th"{_selected(language, "th")}>Thai</option>
            <option value="en"{_selected(language, "en")}>English</option>
          </select></label>
          <label>LINE Webhook<input name="notifications.line_webhook_url" value="{_h(notifications.get('line_webhook_url') or '')}"></label>
          <label>Google Chat Webhook<input name="notifications.google_chat_webhook_url" value="{_h(notifications.get('google_chat_webhook_url') or '')}"></label>
        </div>
        <div class="settings-card">
          <h2>Security</h2>
          <p class="muted">Admin login, enroll token, and agent token enforcement are managed from server secrets so they are not exposed in the browser.</p>
        </div>
        <div class="settings-card">
          <h2>Retention</h2>
          <p class="muted">Event retention removes old log events only. Incident memory is retained so repeated website problems can be recognized faster.</p>
        </div>
        <div class="settings-card system-info-card">
          <h2>System Health</h2>
          <p class="muted">System Info</p>
          <div class="system-info">
            <div><strong>Version</strong><br>1.0.0</div>
            <div><strong>Status</strong><br><span class="status-badge {health_class}">{_h(health_label)}</span></div>
            <div><strong>Database</strong><br>SQLite / {_h(database_status)}</div>
            <div><strong>Storage</strong><br>{_h(data_dir_status)}</div>
            <div><strong>Agents</strong><br>{total_agents} total / {_h(stale_agent_label)}</div>
            <div><strong>Offline Agent IDs</strong><br>{_h(offline_agents)}</div>
            <div><strong>Open Incidents</strong><br>{_h(incidents_health.get('open') or 0)}</div>
            <div><strong>Storage Path</strong><br>{_h(data_dir_health.get('path') or '/data')}</div>
            <div><strong>Server Time</strong><br>{_h(str(health.get('server_time') or settings.get('server_time') or '-'))}</div>
          </div>
        </div>
        <div class="settings-actions">
          <button class="primary-action" type="submit">Save Changes</button>
          <span id="settings-status" class="status-line"></span>
        </div>
      </form>""".rstrip()
