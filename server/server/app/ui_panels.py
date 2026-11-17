from __future__ import annotations

from typing import Any

from .ui_helpers import (
    LOG_PAGE_SIZE, _agent_detail_href, _dashboard_href, _machine_status,
    _relative_label, _render_log_message, _render_log_pagination,
    _selected, _severity_badge_class, _source_detail_href, _source_status_class,
)
from .utils import _compact_page_numbers, _h

def _render_website_overview_detail(
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str,
    log_events: list[dict[str, Any]],
    log_page: int,
    total_log_events: int,
) -> str:
    open_incidents = [incident for incident in incidents if incident.get("status") == "open"]
    problem_events = [event for event in events if event["severity"] in {"warning", "problem", "critical"}]
    critical_events = [event for event in events if event["severity"] == "critical"]
    latest_event = events[0] if events else None
    latest_label = latest_event["category"] if latest_event else "no_data"
    return f"""
      <section class="website-detail">
        <div class="monitor-canvas">
          {_render_machine_tabs(agents, selected_website_id)}
          <div class="monitor-main">
            <div class="monitor-layout">
              <div class="detail-column">
                <section class="website-summary">
                  <div class="detail-head">
                    <div>
                      <h2>{_h(selected_website_id)}</h2>
                      <div class="scope-bar"><strong>Selected Website: {_h(selected_website_id)}</strong></div>
                    </div>
                    <button class="ai-btn" onclick="runAiAnalysis('{_h(selected_website_id)}')">Run AI Diagnostics</button>
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
              </div>
              {_render_ai_side_panel(agents, incidents, events, selected_website_id)}
            </div>
            {_render_log_panel(log_events, selected_website_id, log_page, total_log_events)}
          </div>
        </div>
      </section>""".rstrip()


def _render_machine_tabs(agents: list[dict[str, Any]], selected_website_id: str) -> str:
    if not agents:
        return """
          <nav class="machine-tabs" aria-label="Machines">
            <a class="machine-tab" href="#log-panel" data-machine-tab="none">-<small>No machines</small></a>
          </nav>""".rstrip()
    tabs = "\n".join(
        f"""<a class="machine-tab" href="#machine-{_h(str(agent['agent_id']))}" data-machine-tab="{_h(str(agent['agent_id']))}">
            {index}<small>{_h(str(agent['agent_id']))}</small>
          </a>""".rstrip()
        for index, agent in enumerate(agents, start=1)
    )
    return f"""
          <nav class="machine-tabs" aria-label="{_h(selected_website_id)} machines">
            {tabs}
          </nav>""".rstrip()


def _fmt_thai_time(raw_ts: Any) -> str:
    from datetime import datetime, timedelta, timezone
    txt = str(raw_ts or "").strip()
    if not txt or txt == "-":
        return "-"
    try:
        norm = txt[:-1] + "+00:00" if txt.endswith("Z") else txt
        dt = datetime.fromisoformat(norm)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        bkk = dt.astimezone(timezone(timedelta(hours=7)))
        return bkk.strftime("%Y-%m-%d %H:%M:%S")
    except ValueError:
        return txt[:19].replace("T", " ")


def _infer_incident_ai_impact(title: str, machine_id: str, sev: str, ai_summary: str) -> str:
    clean_ai = str(ai_summary or "").strip()
    if clean_ai:
        first_line = clean_ai.splitlines()[0].strip()
        return first_line if len(first_line) <= 130 else first_line[:127] + "..."
    low = title.lower()
    m = machine_id or "เซิร์ฟเวอร์"
    if "disk_full" in low or "no space" in low:
        return f"🚨 AI วิเคราะห์: พื้นที่ดิสก์บน {m} เต็ม ส่งผลกระทบโดยตรงให้เขียนข้อมูล/Log ไม่ได้ เสี่ยงทำให้เว็บไซต์ล่ม"
    if "too_many_connections" in low or "max_connections" in low:
        return f"🚨 AI วิเคราะห์: ฐานข้อมูล {m} คิวเชื่อมต่อเต็ม ส่งผลให้หน้าเว็บโหลดค้างหรือเกิด 502/504"
    if "connection_refused" in low:
        return f"⚠️ AI วิเคราะห์: บริการบน {m} ปฏิเสธการเชื่อมต่อ ส่งผลกระทบต่อการเรียกใช้งานของระบบเว็บ"
    if "timeout" in low or "upstream_timeout" in low:
        return f"⚠️ AI วิเคราะห์: การเชื่อมต่อที่ {m} ตอบสนองช้าเกินกำหนด (Timeout) ส่งผลให้หน้าเว็บตอบสนองช้า"
    if "permission_denied" in low:
        return f"⚠️ AI วิเคราะห์: สิทธิ์การเข้าถึงไฟล์/บริการบน {m} ถูกปฏิเสธ อาจทำให้บางฟีเจอร์ของเว็บทำงานไม่สมบูรณ์"
    if "agent_data_loss" in low or "offline" in low:
        return f"⚠️ AI วิเคราะห์: สัญญาณจากเครื่อง {m} ขาดหายชั่วคราว ควรตรวจสอบสถานะเครือข่ายหรือโหนดในคลัสเตอร์"
    return f"🤖 AI วิเคราะห์:ตรวจพบสัญญาณระดับ {sev.upper()} บน {m} ที่อาจส่งผลกระทบต่อเสถียรภาพของเว็บไซต์"


def _render_incidents_panel(
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]] | None = None,
) -> str:
    import json as _json
    events = events or []
    sev_rank = {"critical": 3, "problem": 2, "warning": 1}

    grouped: dict[tuple[str, str, str], dict[str, Any]] = {}
    for incident in incidents:
        if str(incident.get("status") or "").lower() == "false_positive":
            continue
        web_id = str(incident.get("website_id") or "-")
        title = str(incident.get("title") or "").strip()
        first_seen = str(incident.get("first_seen_at") or incident.get("started_at") or incident.get("last_seen_at") or "")
        last_seen = str(incident.get("last_seen_at") or first_seen)
        day_key = _fmt_thai_time(last_seen)[:10]
        key = (web_id, title, day_key)
        count = int(incident.get("event_count") or 1)
        sev = str(incident.get("severity") or "warning").lower()
        fp = str(incident.get("fingerprint") or "")
        inc_id = str(incident.get("incident_id") or "")
        ai_sum = str(incident.get("ai_summary") or "").strip()

        if key not in grouped:
            grouped[key] = {
                "incident_id": inc_id,
                "website_id": web_id,
                "title": title,
                "day_key": day_key,
                "first_seen_at": first_seen,
                "last_seen_at": last_seen,
                "event_count": count,
                "severity": sev,
                "ai_summary": ai_sum,
                "fingerprints": {fp} if fp else set(),
            }
        else:
            g = grouped[key]
            g["event_count"] += count
            if first_seen and (not g["first_seen_at"] or first_seen < g["first_seen_at"]):
                g["first_seen_at"] = first_seen
            if last_seen and last_seen > g["last_seen_at"]:
                g["last_seen_at"] = last_seen
                g["incident_id"] = inc_id
            if sev_rank.get(sev, 0) > sev_rank.get(g["severity"], 0):
                g["severity"] = sev
            if ai_sum and not g.get("ai_summary"):
                g["ai_summary"] = ai_sum
            if fp:
                g["fingerprints"].add(fp)

    merged_list = sorted(
        grouped.values(),
        key=lambda item: str(item.get("last_seen_at") or ""),
        reverse=True,
    )

    incident_rows = []
    for item in merged_list:
        inc_id = str(item["incident_id"])
        web_id = str(item["website_id"])
        title = str(item["title"])
        day_key = str(item.get("day_key") or "")
        fps: set[str] = item["fingerprints"]
        first_fmt = _fmt_thai_time(item["first_seen_at"])
        last_fmt = _fmt_thai_time(item["last_seen_at"])
        count = int(item["event_count"])
        sev = str(item["severity"])

        machine_id = ""
        if " on " in title:
            machine_id = title.rsplit(" on ", 1)[-1].strip()

        matched_events = [
            e for e in events
            if (str(e.get("fingerprint") or "") in fps)
            or (
                str(e.get("website_id") or "") == web_id
                and (not machine_id or str(e.get("agent_id") or "") == machine_id)
                and e.get("severity") in {"warning", "problem", "critical"}
            )
        ][:8]
        if not machine_id and matched_events:
            machine_id = str(matched_events[0].get("agent_id") or "")

        ai_impact = _infer_incident_ai_impact(title, machine_id, sev, str(item.get("ai_summary") or ""))

        evidence_lines = [
            f"[{_fmt_thai_time(e.get('timestamp'))}] {e.get('agent_id', '-')} ({e.get('category', '-')}): {e.get('message', '')}"
            for e in matched_events
        ]
        if not evidence_lines:
            evidence_lines = [f"[{last_fmt}] {web_id} / {machine_id or 'node'}: {title}"]
        evidence_json = _h(_json.dumps(evidence_lines, ensure_ascii=False))

        incident_rows.append(
            f"<tr class='incident-row' data-incident-date='{_h(day_key)}'>"
            f"<td class='log-time' style='white-space:nowrap;font-size:15px;'><strong>{_h(last_fmt)}</strong><div class='muted' style='font-size:13px;margin-top:4px;'>เริ่มพบ: {_h(first_fmt)}</div></td>"
            f"<td style='font-size:15px;'><strong>{_h(web_id)}</strong><div class='muted' style='font-size:13.5px;margin-top:4px;'>เครื่อง: {_h(machine_id or '-')}</div></td>"
            f"<td><span class='status-badge {_severity_badge_class(sev)}' style='font-size:13px;padding:5px 10px;'>{_h(sev)}</span></td>"
            f"<td style='font-size:15.5px;'><strong>{_h(title)}</strong><div style='font-size:14px;margin-top:5px;color:#1e293b;line-height:1.45;'>{_h(ai_impact)}</div></td>"
            f"<td style='display:flex;gap:6px;flex-wrap:wrap;'>"
            f"<button type='button' class='ai-btn-sm' style='font-size:14px;padding:8px 14px;' "
            f"data-inc-id='{_h(inc_id)}' data-inc-web='{_h(web_id)}' data-inc-machine='{_h(machine_id or '-')}' "
            f"data-inc-title='{_h(title)}' data-inc-sev='{_h(sev)}' data-inc-count='{count}' "
            f"data-inc-ai='{_h(ai_impact)}' "
            f"data-inc-first='{_h(first_fmt)}' data-inc-last='{_h(last_fmt)}' data-inc-evidence='{evidence_json}' "
            f"onclick='openIncidentDetailModal(this)'>🔍 ดูสาเหตุ &amp; Log</button>"
            f"<button type='button' class='secondary' style='font-size:13.5px;padding:7px 12px;color:#b42318;border-color:#fda29b;' "
            f"data-inc-id='{_h(inc_id)}' data-inc-web='{_h(web_id)}' data-inc-title='{_h(title)}' "
            f"onclick='suppressIncidentRow(this)' title='ทำเครื่องหมายว่าไม่ใช่ปัญหา และไม่แจ้งเตือนซ้ำ'>🚫 ไม่ใช่ปัญหา</button>"
            f"<button class='close-btn-sm' data-close='{_h(inc_id)}' hidden style='display:none !important;'>Close</button>"
            f"</td></tr>"
        )
    rows_html = "\n".join(incident_rows)
    return f"""
      <section class="incident-panel" id="incidents-panel">
        <div class="detail-head" style="margin-bottom: 14px; display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; gap: 12px;">
          <div>
            <h2 style="margin: 0; font-size: 20px;">Active Incidents (ฐานข้อมูลประวัติเหตุการณ์ถาวร)</h2>
          </div>
          <div style="display: flex; align-items: center; gap: 10px;">
            <label style="font-size: 14.5px; font-weight: 700; display: flex; align-items: center; gap: 8px; margin: 0;">
              📅 เลือกวันที่:
              <input type="date" id="incident-date-filter" onchange="filterIncidentsByDate()" style="padding: 6px 12px; border: 1px solid var(--border); border-radius: 6px; font-size: 14px;">
            </label>
            <button type="button" class="secondary" onclick="clearIncidentDateFilter()" style="padding: 6px 14px; font-size: 14px;">ดูทุกวัน</button>
          </div>
        </div>
        <table>
          <thead>
            <tr style="font-size: 13.5px;">
              <th style="font-size: 13.5px; padding: 12px;">วัน-เวลาล่าสุด (Time)</th>
              <th style="font-size: 13.5px; padding: 12px;">เว็บไซต์ / เครื่อง</th>
              <th style="font-size: 13.5px; padding: 12px;">Severity</th>
              <th style="font-size: 13.5px; padding: 12px;">เหตุการณ์ &amp; ผลวิเคราะห์ AI (Incident &amp; AI Impact)</th>
              <th style="font-size: 13.5px; padding: 12px;">Action</th>
            </tr>
          </thead>
          <tbody id="incidents-tbody">{rows_html or '<tr><td colspan="5">No registered incidents in this scope</td></tr>'}</tbody>
        </table>
      </section>
      <div id="incident-detail-modal" class="modal-overlay" style="display:none;">
        <div class="modal-card" style="max-width:640px;">
          <div class="modal-header">
            <h3 id="incident-detail-modal-title">🔍 รายละเอียดเหตุการณ์และหลักฐาน Log</h3>
            <button type="button" class="close-btn" onclick="closeIncidentDetailModal()">&times;</button>
          </div>
          <div class="modal-body" id="incident-detail-modal-body"></div>
        </div>
      </div>""".rstrip()


def _render_log_panel(log_events: list[dict[str, Any]], selected_website_id: str, log_page: int, total_log_events: int) -> str:
    event_rows = "\n".join(
        f"<tr><td class='log-time'>{_h(event['timestamp'])}</td><td><strong>{_h(event['agent_id'])}</strong></td>"
        f"<td><span class='status-badge {_severity_badge_class(str(event['severity']))}'>{_h(event['severity'])}</span></td>"
        f"<td class='log-cat'>{_h(event['category'])}</td><td class='log-message'>{_render_log_message(event['message'])}</td></tr>"
        for event in log_events
    )
    return f"""
      <section class="log-panel" id="log-panel">
        <h2>Operations Log Stream</h2>
        <table>
          <thead><tr><th>Ingest Time</th><th>Machine</th><th>Severity</th><th>Category</th><th>Message</th></tr></thead>
          <tbody>{event_rows or '<tr><td colspan="5">No operations logs registered</td></tr>'}</tbody>
        </table>
        {_render_log_pagination(selected_website_id, log_page, total_log_events)}
      </section>""".rstrip()


def _render_agents_panel(agents: list[dict[str, Any]], selected_website_id: str, public_url: str) -> str:
    default_website = selected_website_id or "website_1"
    server_url = (public_url or "http://10.1.0.10:8888").rstrip("/")
    install_command = (
        "./install-agent.sh "
        f"--server-url {server_url} "
        "--enroll-token <ENROLL_TOKEN> "
        "--name <machine-name> "
        "--role web "
        f"--website-id {default_website}"
    )
    agent_row_parts = []
    for agent in agents:
        agent_id = str(agent.get("agent_id") or "")
        web_id = str(agent.get("website_id") or "-")
        role_val = str(agent.get("agent_role") or "web")
        host_val = str(agent.get("hostname") or "-")
        cluster_val = str(agent.get("cluster_id") or "")
        agent_status = str(agent.get("health_status") or agent.get("status") or "")
        status_class = _severity_badge_class("ok" if agent_status in {"active", "online"} else "warning")
        agent_row_parts.append(
            f"<tr>"
            f"<td><strong class='agent-name'>{_h(agent_id)}</strong></td>"
            f"<td>{_h(web_id)}</td>"
            f"<td><span style='font-family: monospace; opacity: 0.85;'>{_h(role_val)}</span></td>"
            f"<td><span class='status-badge {status_class}'>{_h(agent_status)}</span></td>"
            f"<td>{_h(host_val)}</td>"
            f"<td class='log-time'>{_h(_fmt_thai_time(agent['last_seen_at']))}</td>"
            f"<td style='display:flex;gap:6px;'>"
            f"<button type='button' class='er-vm-edit-btn' onclick=\"openAgentListEditModal('{_h(agent_id)}', '{_h(host_val if host_val != '-' else agent_id)}', '{_h(role_val)}', '{_h(web_id if web_id != '-' else default_website)}', '{_h(cluster_val)}')\">✏️ แก้ไข</button>"
            f"</td></tr>"
        )
    agent_rows = "\n".join(agent_row_parts)
    return f"""
      <div class="detail-column">
        <section class="install-card">
          <div>
            <h2>Install Command Generator</h2>
            <div>Deploy AI Log Monitor agents to Linux machines with the selected website scope.</div>
          </div>
          <div class="install-inner">
            <h3>Generate Install Command</h3>
            <div class="install-fields">
              <div class="install-field"><strong>{_h(server_url)}</strong><span>Server URL</span></div>
              <div class="install-field"><strong>{_h(default_website)}</strong><span>Website ID</span></div>
              <div class="install-field"><strong>web</strong><span>Default role</span></div>
            </div>
            <div class="command-box">{_h(install_command)}</div>
            <button type="button" class="secondary">Copy Command</button>

            <div style="margin-top: 16px; padding: 16px 20px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 10px; font-size: 16.5px; line-height: 1.75;">
              <strong style="display:block; margin-bottom: 10px; color: #0f172a; font-size: 18px;">📘 คู่มือการตั้งค่าคำสั่งติดตั้ง และตำแหน่งไฟล์คอนฟิกของ Agent บนเครื่องปลายทาง</strong>
              <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px;">
                <div>
                  <div style="font-weight: 700; color: #1e293b; margin-bottom: 6px; font-size: 17px;">1) พารามิเตอร์ที่ต้องระบุตอนติดตั้ง:</div>
                  <ul style="margin: 0; padding-left: 20px; color: #334155;">
                    <li><code style="font-size:15.5px;font-weight:700;">--server-url</code> : URL ของเซิร์ฟเวอร์แม่ข่าย ({_h(server_url)})</li>
                    <li><code style="font-size:15.5px;font-weight:700;">--enroll-token</code> : รหัสลงทะเบียนเครื่อง (ตรงกับค่า <code>ENROLL_TOKEN</code> บนเซิร์ฟเวอร์)</li>
                    <li><code style="font-size:15.5px;font-weight:700;">--name</code> : ชื่อเครื่องที่จะแสดงในหน้าผัง ER Diagram (เช่น <code>web1</code>, <code>db1</code>)</li>
                    <li><code style="font-size:15.5px;font-weight:700;">--role</code> : ประเภทเครื่อง (<code>web</code>, <code>app</code>, <code>db</code>, <code>lb</code>, <code>cache</code>) เพื่อค้นหาไฟล์ Log อัตโนมัติ</li>
                    <li><code style="font-size:15.5px;font-weight:700;">--website-id</code> : ชื่อวงเว็บไซต์ (เช่น <code>{_h(default_website)}</code>, <code>web_sit</code>, <code>web_uat</code>, <code>web_prod</code>)</li>
                  </ul>
                </div>
                <div>
                  <div style="font-weight: 700; color: #1e293b; margin-bottom: 6px; font-size: 17px;">2) ตำแหน่งไฟล์เมื่อต้องการเข้าไปแก้ไขภายหลังบนเครื่อง VM:</div>
                  <ul style="margin: 0; padding-left: 20px; color: #334155;">
                    <li>📄 <strong>ไฟล์ตั้งค่า Agent (Config)</strong> : <code style="font-size:15.5px;font-weight:700;">/etc/ai-log-agent/agent.yaml</code><br><span class="muted" style="font-size:15px;">(ใช้แก้ <code>server_url</code>, <code>website_id</code>, <code>agent_id</code>, <code>agent_role</code> หรือระบุ Path ไฟล์ Log เพิ่มเติม)</span></li>
                    <li>⚙️ <strong>ไฟล์ Systemd Service</strong> : <code style="font-size:15.5px;font-weight:700;">/etc/systemd/system/ai-log-agent.service</code></li>
                    <li>🔄 <strong>คำสั่งรีสตาร์ทหลังแก้คอนฟิก</strong> : <code style="font-size:15.5px;font-weight:700;">sudo systemctl daemon-reload &amp;&amp; sudo systemctl restart ai-log-agent</code></li>
                    <li>📊 <strong>คำสั่งตรวจสอบสถานะ Agent</strong> : <code style="font-size:15.5px;font-weight:700;">sudo systemctl status ai-log-agent</code></li>
                  </ul>
                </div>
              </div>
            </div>
          </div>
        </section>
        <section class="incident-panel">
          <h2>Server List</h2>
          <div class="muted">Agents Registry (สามารถกด ✏️ แก้ไขชื่อ/บทบาท/เว็บไซต์ หรือ 🗑️ ลบเครื่องออกจากระบบได้ทันที)</div>
          <table id="agents-table">
            <thead><tr><th>Agent</th><th>Website</th><th>Role</th><th>Status</th><th>Hostname</th><th>Last Seen</th><th>Action</th></tr></thead>
            <tbody>{agent_rows or '<tr><td colspan="7">No agents connected</td></tr>'}</tbody>
          </table>
        </section>
        <div id="er-item-edit-modal" class="modal-overlay" style="display:none;">
          <div class="modal-card" style="max-width:440px;">
            <div class="modal-header">
              <h3 id="er-edit-modal-title">✏️ แก้ไขข้อมูลเครื่องเซิร์ฟเวอร์</h3>
              <button type="button" class="close-btn" onclick="closeErEditModal()">&times;</button>
            </div>
            <div class="modal-body" id="er-edit-modal-body"></div>
          </div>
        </div>
      </div>""".rstrip()


def _render_import_panel(website_options: str, selected_website_id: str) -> str:
    return f"""
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
      </section>""".rstrip()


def _render_admin_panel(website_rows: str, agent_rows: str, incident_rows: str, event_rows: str) -> str:
    return f"""
      <div class="detail-column">
        <section class="data-shell">
          <details open>
            <summary>Advanced Admin Options</summary>
            <div style="display: grid; gap: 16px; margin-top: 14px;">
              <form id="create-website" class="advanced-grid">
                <strong>Register Website</strong>
                <label>Website ID<input name="website_id" placeholder="website_1" required></label>
                <label>Friendly Name<input name="name" placeholder="Website Name" required></label>
                <button type="submit" class="secondary">Create Website</button>
              </form>
              <form id="assign-agent" class="advanced-grid">
                <strong>Bind Agent</strong>
                <label>Agent ID<input name="agent_id" placeholder="web01" required></label>
                <label>Website ID<input name="website_id" placeholder="website_1" required></label>
                <label>Agent Role<input name="agent_role" placeholder="web"></label>
                <button type="submit" class="secondary">Bind Agent</button>
              </form>
              <form id="agent-maintenance-form" class="advanced-grid">
                <strong>Agent Maintenance Window</strong>
                <label>Agent ID<input name="agent_id" placeholder="web01" required></label>
                <label>Duration (minutes, 0 to clear)<input name="minutes" type="number" min="0" value="60" required></label>
                <button type="submit" class="secondary">Set Maintenance</button>
              </form>
            </div>
          </details>
        </section>
        <section class="data-shell">
          <details open>
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
      </div>""".rstrip()


def _render_website_detail(
    agents: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    selected_website_id: str,
    log_events: list[dict[str, Any]],
    log_page: int,
    total_log_events: int,
) -> str:
    open_incidents = [incident for incident in incidents if incident.get("status") == "open"]
    problem_events = [event for event in events if event["severity"] in {"warning", "problem", "critical"}]
    critical_events = [event for event in events if event["severity"] == "critical"]
    latest_event = events[0] if events else None
    latest_label = latest_event["category"] if latest_event else "no_data"
    incident_rows = "\n".join(
        f"<tr><td><span class='status-badge {_severity_badge_class(incident['severity'])}'>{_h(incident['severity'])}</span></td>"
        f"<td><span class='status-badge {_severity_badge_class('warning' if incident['status']=='open' else 'ok')}'>{_h(incident['status'])}</span></td>"
        f"<td><strong>{_h(incident['title'])}</strong></td><td>{incident['event_count']}</td>"
        f"<td class='log-time'>{_h(incident['last_seen_at'])}</td>"
        f"<td><button class='close-btn-sm' data-close='{_h(incident['incident_id'])}'>Close</button></td></tr>"
        for incident in incidents
    )
    event_rows = "\n".join(
        f"<tr><td class='log-time'>{_h(event['timestamp'])}</td><td><strong>{_h(event['agent_id'])}</strong></td>"
        f"<td><span class='status-badge {_severity_badge_class(str(event['severity']))}'>{_h(event['severity'])}</span></td>"
        f"<td class='log-cat'>{_h(event['category'])}</td><td class='log-message'>{_render_log_message(event['message'])}</td></tr>"
        for event in log_events
    )
    pagination = _render_log_pagination(selected_website_id, log_page, total_log_events)
    return f"""
      <section class="website-detail">
        <div class="detail-column">
          <section class="website-summary">
            <div class="detail-head">
              <div>
                <h2>{_h(selected_website_id)}</h2>
                <div class="scope-bar"><strong>Selected Website: {_h(selected_website_id)}</strong></div>
              </div>
              <button class="ai-btn" onclick="runAiAnalysis('{_h(selected_website_id)}')">Run AI Diagnostics</button>
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
            {pagination}
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
          <a id="machine-{_h(agent_id)}" class="machine-card {status_class}" href="{_h(_dashboard_href('logs', selected_website_id))}" data-machine="{_h(agent_id)}">
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
          <div class="machine-latest-message" title="{_h(latest_message)}">{_h(latest_message)}</div>
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
        <a class="ai-btn-sm" href="{_h(_dashboard_href('logs', selected_website_id))}" style="text-decoration: none; width: fit-content;">View Logs</a>
      </div>
      <div class="ai-box">
        <h3>Log Evidence</h3>
        {evidence_lines}
      </div>
    </aside>""".rstrip()
