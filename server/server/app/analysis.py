from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .ai_settings import DEFAULT_AI_SETTINGS, load_ai_settings, save_ai_settings
from .http_client import HttpPost, _http_post_json
from .notifications import send_alert_notifications
from .privacy import redact_text
from .storage import Store


def build_mock_ai_report(store: Store, website_id: str, limit: int = 100) -> dict[str, Any]:
    settings = _deep_copy(DEFAULT_AI_SETTINGS)
    settings["analysis"]["max_context_events"] = limit
    return build_ai_report(store, website_id, settings=settings)


def build_ai_report(
    store: Store,
    website_id: str,
    settings: dict[str, Any] | None = None,
    config_path: Path | None = None,
    http_post: HttpPost | None = None,
) -> dict[str, Any]:
    active_settings = settings or load_ai_settings(config_path)
    analysis_settings = active_settings.get("analysis", {})
    limit = int(analysis_settings.get("max_context_events") or 100)
    window_minutes = int(analysis_settings.get("time_window_minutes") or 0)
    since = _context_since(store, website_id, window_minutes)
    events = _expand_embedded_context(store.website_context(website_id, limit=limit, since=since))
    problem_events = [event for event in events if event["severity"] in {"warning", "problem", "critical"}]
    topology_hints = store.list_topology_hints(website_id)

    er_graph: dict[str, Any] = {}
    if hasattr(store, "build_er_topology_graph"):
        try:
            er_graph = store.build_er_topology_graph(website_id) or {}
        except Exception:
            er_graph = {}

    vm_relations: list[dict[str, Any]] = []
    if hasattr(store, "list_vm_relations"):
        try:
            vm_relations = list(store.list_vm_relations(website_id) or [])
        except Exception:
            vm_relations = []
    if not vm_relations and isinstance(er_graph, dict):
        vm_relations = list(er_graph.get("relations") or er_graph.get("edges") or [])

    website_agents = _website_agents_map(store, website_id, er_graph)

    events, problem_events, analysis_sequence = _targeted_context(
        events,
        problem_events,
        topology_hints,
        vm_relations=vm_relations,
        er_graph=er_graph,
        website_agents=website_agents,
    )
    fingerprints = sorted({event["fingerprint"] for event in problem_events})
    memory_matches = store.match_incident_memory(website_id, fingerprints)
    report = _build_rule_report(website_id, events, problem_events, memory_matches, topology_hints, window_minutes)
    primary_agent = analysis_sequence[0] if analysis_sequence else None
    report["primary_agent"] = primary_agent
    report["analysis_sequence"] = analysis_sequence
    report["er_topology"] = er_graph
    report["cascading_timeline"] = _build_cascading_timeline(
        website_id=website_id,
        primary_agent=primary_agent,
        analysis_sequence=analysis_sequence,
        problem_events=problem_events,
        website_agents=website_agents,
        er_graph=er_graph,
        vm_relations=vm_relations,
        topology_hints=topology_hints,
    )
    report["thai_summary"] = _build_thai_cascading_summary(
        website_id=website_id,
        report=report,
        primary_agent=primary_agent,
        analysis_sequence=analysis_sequence,
        cascading_timeline=report["cascading_timeline"],
    )

    mode = str(active_settings.get("ai", {}).get("mode") or "mock").lower()
    enabled = bool(active_settings.get("ai", {}).get("enabled", True))
    if enabled and mode in {"ollama", "api"} and problem_events:
        prompt = _build_prompt(
            website_id,
            events,
            problem_events,
            memory_matches,
            topology_hints,
            window_minutes,
            active_settings,
            er_graph=er_graph,
            cascading_timeline=report["cascading_timeline"],
        )
        llm_text = _call_configured_ai(active_settings, prompt, http_post=http_post)
        if llm_text:
            report["mode"] = mode
            report["summary"] = llm_text
            report["provider"] = active_settings.get("ai", {}).get("provider") or mode
            report["confidence"] = max(float(report["confidence"]), 0.72)
        else:
            report["provider"] = "fallback_mock"
    else:
        report["provider"] = "none"

    _remember_pattern(store, report, problem_events, active_settings, bool(memory_matches))
    if problem_events and hasattr(store, "update_incident_ai_summary"):
        try:
            summary_txt = str(report.get("thai_summary") or report.get("root_cause") or report.get("summary") or "").strip()
            if summary_txt:
                store.update_incident_ai_summary(website_id, summary_txt, float(report.get("confidence") or 0.75))
        except Exception:
            pass
    return report


def _expand_embedded_context(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for event in events:
        metadata = dict(event.get("metadata") or {})
        for context in metadata.get("context_before") or []:
            item = dict(context)
            item.setdefault("website_id", event.get("website_id"))
            item.setdefault("agent_id", event.get("agent_id"))
            item.setdefault("agent_role", event.get("agent_role"))
            item.setdefault("severity", "normal")
            item.setdefault("category", "normal")
            item.setdefault("fingerprint", "")
            expanded.append(item)
        expanded.append(event)
    return expanded


def _website_agents_map(
    store: Store,
    website_id: str,
    er_graph: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    agents_map: dict[str, dict[str, Any]] = {}
    if hasattr(store, "list_agents"):
        try:
            for item in store.list_agents() or []:
                if str(item.get("website_id") or "") == website_id:
                    aid = str(item.get("agent_id") or "").strip()
                    if aid:
                        agents_map[aid] = dict(item)
        except Exception:
            pass
    if isinstance(er_graph, dict):
        for node in er_graph.get("nodes") or er_graph.get("entities") or []:
            if isinstance(node, dict):
                aid = str(node.get("agent_id") or node.get("id") or "").strip()
                if aid:
                    merged = dict(agents_map.get(aid) or {})
                    merged.update(node)
                    agents_map[aid] = merged
    return agents_map


def _normalize_agent_ref(value: Any) -> str:
    text = str(value or "").strip()
    if ":" in text:
        return text.split(":", 1)[0].strip()
    return text


def _extract_relation_endpoints(rel: dict[str, Any]) -> tuple[str, str, str]:
    src = _normalize_agent_ref(
        rel.get("source_agent_id")
        or rel.get("from_agent_id")
        or rel.get("from_agent")
        or rel.get("source")
        or rel.get("agent_id")
    )
    dst = _normalize_agent_ref(
        rel.get("target_agent_id")
        or rel.get("to_agent_id")
        or rel.get("to_agent")
        or rel.get("target")
    )
    rel_type = str(
        rel.get("relation_type")
        or rel.get("type")
        or rel.get("hint_type")
        or "CONNECTED_TO"
    ).upper()
    return src, dst, rel_type


def _event_layer_rank(event: dict[str, Any], website_agents: dict[str, dict[str, Any]] | None = None) -> int:
    cat = str(event.get("category") or "").lower()
    if cat in {"out_of_memory", "disk_full", "agent_data_loss"} or str(event.get("severity") or "") == "critical":
        return 1
    aid = str(event.get("agent_id") or "")
    role = str(event.get("agent_role") or "").lower()
    if not role and website_agents and aid in website_agents:
        role = str(website_agents[aid].get("agent_role") or "").lower()
    if role == "db" or cat in {"db_too_many_connections"}:
        return 2
    if role == "app":
        return 3
    if role in {"web", "lb"} or cat in {"upstream_timeout", "http_5xx", "http_4xx"}:
        return 4
    return 3


def _targeted_context(
    events: list[dict[str, Any]],
    problem_events: list[dict[str, Any]],
    topology_hints: list[dict[str, Any]],
    vm_relations: list[dict[str, Any]] | None = None,
    er_graph: dict[str, Any] | None = None,
    website_agents: dict[str, dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Start with the failing agent and expand to evidenced dependencies and ER relations."""
    if not problem_events:
        return events, problem_events, sorted({str(event["agent_id"]) for event in events})

    ranked_problems = sorted(
        problem_events,
        key=lambda ev: (_event_layer_rank(ev, website_agents), str(ev.get("timestamp") or "")),
    )
    primary_agent = str(ranked_problems[0]["agent_id"])
    known_agents = {str(event["agent_id"]) for event in events}
    if website_agents:
        known_agents.update(website_agents.keys())
    related_agents = {primary_agent}

    for hint in topology_hints:
        hint_agent = str(hint.get("agent_id") or "")
        target = str(hint.get("target") or "")
        target_base = _normalize_agent_ref(target)
        if hint_agent == primary_agent:
            if target in known_agents:
                related_agents.add(target)
            elif target_base in known_agents:
                related_agents.add(target_base)
        if (target == primary_agent or target_base == primary_agent) and hint_agent in known_agents:
            related_agents.add(hint_agent)

    primary_events = [event for event in problem_events if str(event["agent_id"]) == primary_agent]
    primary_categories = {str(event.get("category") or "") for event in primary_events}
    db_pressure = {"db_too_many_connections", "db_error", "database"}
    connection_failures = {"upstream_timeout", "timeout", "connection_refused"}
    if primary_categories & db_pressure:
        related_agents.update(
            str(event["agent_id"])
            for event in problem_events
            if str(event.get("category") or "") in connection_failures
        )
    if primary_categories & connection_failures:
        related_agents.update(
            str(event["agent_id"])
            for event in problem_events
            if str(event.get("category") or "") in db_pressure
        )

    primary_text = " ".join(str(event.get("message") or "").lower() for event in primary_events)
    for agent_id in known_agents:
        if agent_id != primary_agent and agent_id.lower() in primary_text:
            related_agents.add(agent_id)

    # Expand via ER topology relations (PEER_SYNC, ROUTE_TO, REPLICATE) and same-cluster siblings
    er_relations = list(vm_relations or [])
    if isinstance(er_graph, dict):
        for rel in er_graph.get("relations") or er_graph.get("edges") or []:
            if isinstance(rel, dict) and rel not in er_relations:
                er_relations.append(rel)

    # 1. Same cluster siblings
    if website_agents and primary_agent in website_agents:
        primary_cluster = str(website_agents[primary_agent].get("cluster_id") or "").strip()
        if primary_cluster:
            for aid, info in website_agents.items():
                if str(info.get("cluster_id") or "").strip() == primary_cluster:
                    related_agents.add(aid)

    if isinstance(er_graph, dict):
        for cluster in er_graph.get("clusters") or []:
            if not isinstance(cluster, dict):
                continue
            members = [
                str(m.get("agent_id") if isinstance(m, dict) else m)
                for m in (cluster.get("members") or cluster.get("nodes") or cluster.get("agent_ids") or [])
            ]
            if primary_agent in members:
                for member_id in members:
                    if member_id:
                        related_agents.add(member_id)

    # 2. Multi-hop traversal over PEER_SYNC, ROUTE_TO, REPLICATE (and general ER relations)
    traversable_types = {"PEER_SYNC", "ROUTE_TO", "REPLICATE", "FAILOVER_TO", "DEPENDS_ON", "UPSTREAM"}
    frontier = set(related_agents)
    for _hop in range(2):
        next_frontier: set[str] = set()
        for rel in er_relations:
            if not isinstance(rel, dict):
                continue
            src, dst, rel_type = _extract_relation_endpoints(rel)
            if not src or not dst:
                continue
            if rel_type in traversable_types or True:
                if src in frontier and dst not in related_agents:
                    next_frontier.add(dst)
                if dst in frontier and src not in related_agents:
                    next_frontier.add(src)
        if not next_frontier:
            break
        related_agents.update(next_frontier)
        frontier = next_frontier

    sequence = [primary_agent] + sorted(related_agents - {primary_agent})
    rank = {agent_id: index for index, agent_id in enumerate(sequence)}
    scoped_events = [event for event in events if str(event["agent_id"]) in related_agents]
    scoped_events.sort(key=lambda event: rank.get(str(event["agent_id"]), 999))
    scoped_problems = [event for event in scoped_events if event["severity"] in {"warning", "problem", "critical"}]
    return scoped_events, scoped_problems, sequence


def _build_cascading_timeline(
    website_id: str,
    primary_agent: str | None,
    analysis_sequence: list[str],
    problem_events: list[dict[str, Any]],
    website_agents: dict[str, dict[str, Any]],
    er_graph: dict[str, Any],
    vm_relations: list[dict[str, Any]],
    topology_hints: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not primary_agent:
        return []

    timeline: list[dict[str, Any]] = []
    primary_info = dict(website_agents.get(primary_agent) or {})

    # Extract vitals from agent record or latest problem event metadata
    cpu = primary_info.get("cpu_percent")
    ram = primary_info.get("ram_percent")
    disk = primary_info.get("disk_percent")
    for event in problem_events:
        if str(event.get("agent_id")) == primary_agent:
            meta = dict(event.get("metadata") or {})
            if cpu is None:
                cpu = meta.get("cpu_percent")
            if ram is None:
                ram = meta.get("ram_percent")
            if disk is None:
                disk = meta.get("disk_percent")

    vitals: dict[str, Any] = {}
    vitals_parts: list[str] = []
    if cpu is not None:
        vitals["cpu_percent"] = float(cpu)
        vitals_parts.append(f"CPU {float(cpu):.1f}%")
    if ram is not None:
        vitals["ram_percent"] = float(ram)
        vitals_parts.append(f"RAM {float(ram):.1f}%")
    if disk is not None:
        vitals["disk_percent"] = float(disk)
        vitals_parts.append(f"Disk {float(disk):.1f}%")

    primary_role = str(primary_info.get("agent_role") or "unknown")
    primary_status = str(primary_info.get("status") or "degraded")
    vitals_str = f" ({', '.join(vitals_parts)})" if vitals_parts else ""
    timeline.append(
        {
            "step": 1,
            "stage": "primary_node",
            "agent_id": primary_agent,
            "role": primary_role,
            "status": primary_status,
            "vitals": vitals,
            "title": f"Primary Failing Node: {primary_agent} [{primary_role}]{vitals_str}",
            "detail": (
                f"Node {primary_agent} ({primary_role}) triggered primary alert with status '{primary_status}'"
                f"{vitals_str}."
            ),
        }
    )

    # Step 2: Cluster Quorum impact
    cluster_id = str(primary_info.get("cluster_id") or "").strip()
    cluster_summary: dict[str, Any] | None = None
    if isinstance(er_graph, dict):
        for cluster in er_graph.get("clusters") or []:
            if not isinstance(cluster, dict):
                continue
            cid = str(cluster.get("cluster_id") or cluster.get("id") or cluster.get("name") or "").strip()
            members = [
                str(m.get("agent_id") if isinstance(m, dict) else m)
                for m in (cluster.get("members") or cluster.get("nodes") or cluster.get("agent_ids") or [])
            ]
            if (cluster_id and cid == cluster_id) or (primary_agent in members):
                cluster_summary = cluster
                if not cluster_id:
                    cluster_id = cid
                break

    if cluster_id or cluster_summary:
        if cluster_summary:
            total = int(
                cluster_summary.get("total_nodes")
                or cluster_summary.get("total_members")
                or len(cluster_summary.get("members") or cluster_summary.get("nodes") or [])
                or 1
            )
            healthy = cluster_summary.get("healthy_nodes")
            if healthy is None:
                healthy = cluster_summary.get("online_nodes")
            if healthy is None:
                failing_agents = {str(e.get("agent_id")) for e in problem_events if e.get("severity") == "critical"}
                members = [
                    str(m.get("agent_id") if isinstance(m, dict) else m)
                    for m in (cluster_summary.get("members") or cluster_summary.get("nodes") or [])
                ]
                healthy = sum(
                    1
                    for m in members
                    if m not in failing_agents
                    and str((website_agents.get(m) or {}).get("status") or "active") in {"active", "online", "healthy"}
                )
            healthy = int(healthy)
        else:
            siblings = [
                aid
                for aid, info in website_agents.items()
                if str(info.get("cluster_id") or "").strip() == cluster_id
            ]
            total = len(siblings) or 1
            failing_agents = {str(e.get("agent_id")) for e in problem_events if e.get("severity") == "critical"}
            healthy = sum(
                1
                for aid in siblings
                if aid not in failing_agents
                and str((website_agents.get(aid) or {}).get("status") or "active") in {"active", "online", "healthy"}
            )

        quorum_needed = (total // 2) + 1
        quorum_maintained = healthy >= quorum_needed and total > 1
        quorum_label = (
            f"Cluster {cluster_id}: {healthy}/{total} Quorum Maintained (Failover Active)"
            if quorum_maintained
            else f"Cluster {cluster_id}: {healthy}/{total} Quorum Lost (Service Outage Risk)"
        )
        timeline.append(
            {
                "step": 2,
                "stage": "cluster_quorum",
                "cluster_id": cluster_id,
                "healthy_nodes": healthy,
                "total_nodes": total,
                "quorum_maintained": quorum_maintained,
                "title": quorum_label,
                "detail": (
                    f"{healthy} of {total} cluster members remain healthy (minimum quorum: {quorum_needed}). "
                    + ("HA failover keeps cluster operational." if quorum_maintained else "Quorum lost; immediate intervention required.")
                ),
            }
        )
    else:
        timeline.append(
            {
                "step": 2,
                "stage": "cluster_quorum",
                "cluster_id": None,
                "healthy_nodes": 0,
                "total_nodes": 1,
                "quorum_maintained": False,
                "title": f"Standalone VM ({primary_agent}): Single Point of Failure (No HA Cluster)",
                "detail": f"Node {primary_agent} is not part of a multi-node HA cluster.",
            }
        )

    # Step 3: Upstream/Downstream connected VMs traced via ER relations
    all_relations = list(vm_relations or [])
    if isinstance(er_graph, dict):
        for rel in er_graph.get("relations") or er_graph.get("edges") or []:
            if isinstance(rel, dict) and rel not in all_relations:
                all_relations.append(rel)

    upstream_callers: list[str] = []
    peer_nodes: list[str] = []
    downstream_targets: list[str] = []

    for rel in all_relations:
        if not isinstance(rel, dict):
            continue
        src, dst, rel_type = _extract_relation_endpoints(rel)
        if not src or not dst:
            continue
        if rel_type == "PEER_SYNC":
            if src == primary_agent and dst != primary_agent:
                peer_nodes.append(f"{dst} (PEER_SYNC)")
            elif dst == primary_agent and src != primary_agent:
                peer_nodes.append(f"{src} (PEER_SYNC)")
        elif dst in analysis_sequence and src != dst and src not in peer_nodes:
            if dst == primary_agent or src in analysis_sequence:
                upstream_callers.append(f"{src} --[{rel_type}]--> {dst}")
        elif src == primary_agent and dst != primary_agent:
            downstream_targets.append(f"{src} --[{rel_type}]--> {dst}")

    for hint in topology_hints:
        h_src = str(hint.get("agent_id") or "")
        h_dst = _normalize_agent_ref(hint.get("target"))
        h_type = str(hint.get("hint_type") or "http_upstream")
        if h_dst == primary_agent and h_src != primary_agent:
            upstream_callers.append(f"{h_src} --[{h_type}]--> {h_dst}")
        elif h_src == primary_agent and h_dst != primary_agent:
            downstream_targets.append(f"{h_src} --[{h_type}]--> {h_dst}")

    other_seq = [a for a in analysis_sequence if a != primary_agent]
    trace_parts: list[str] = []
    if peer_nodes:
        trace_parts.append(f"Peers: {', '.join(sorted(set(peer_nodes)))}")
    if upstream_callers:
        trace_parts.append(f"Upstream: {', '.join(sorted(set(upstream_callers)))}")
    if downstream_targets:
        trace_parts.append(f"Downstream: {', '.join(sorted(set(downstream_targets)))}")
    if not trace_parts and other_seq:
        trace_parts.append(f"Connected nodes in sequence: {', '.join(other_seq)}")

    timeline.append(
        {
            "step": 3,
            "stage": "cascading_impact",
            "connected_agents": other_seq,
            "upstream": sorted(set(upstream_callers)),
            "peers": sorted(set(peer_nodes)),
            "downstream": sorted(set(downstream_targets)),
            "title": (
                f"Cascading Topology Trace ({', '.join(other_seq)})"
                if other_seq
                else "Cascading Topology Trace (Isolated Node)"
            ),
            "detail": " | ".join(trace_parts) if trace_parts else f"No dependent upstream/downstream VMs impacted beyond {primary_agent}.",
        }
    )

    return timeline


def _build_thai_cascading_summary(
    website_id: str,
    report: dict[str, Any],
    primary_agent: str | None,
    analysis_sequence: list[str],
    cascading_timeline: list[dict[str, Any]],
) -> str:
    if not primary_agent or not report.get("evidence"):
        return f"ไม่พบสัญญาณผิดปกติในระบบของ {website_id} ทุกโหนดทำงานปกติ"

    step1 = cascading_timeline[0]["title"] if len(cascading_timeline) >= 1 else f"เครื่องต้นตอ: {primary_agent}"
    step2 = cascading_timeline[1]["title"] if len(cascading_timeline) >= 2 else "ไม่มีข้อมูลคลัสเตอร์"
    step3 = cascading_timeline[2]["detail"] if len(cascading_timeline) >= 3 else "ไม่มีโหนดเชื่อมโยง"
    seq_str = " -> ".join(analysis_sequence)

    return (
        f"🔍 วิเคราะห์ผลกระทบลูกโซ่ (Cascading RCA) สำหรับ {website_id}:\n"
        f"1️⃣ จุดเกิดเหตุหลัก: {step1}\n"
        f"2️⃣ สถานะคลัสเตอร์ (Quorum): {step2}\n"
        f"3️⃣ เส้นทางผลกระทบตามผัง ER ({seq_str}): {step3}\n"
        f"💡 สาเหตุรากฐาน: {report.get('root_cause')}\n"
        f"🛠️ แนวทางแก้ไข: {report.get('recommended_action')}"
    )


def _build_rule_report(
    website_id: str,
    events: list[dict[str, Any]],
    problem_events: list[dict[str, Any]],
    memory_matches: list[dict[str, Any]],
    topology_hints: list[dict[str, Any]],
    window_minutes: int,
) -> dict[str, Any]:
    agents = sorted({event["agent_id"] for event in events})
    categories = Counter(event["category"] for event in problem_events)
    fingerprints = sorted({event["fingerprint"] for event in problem_events})
    evidence = [
        f"{event['timestamp']} {event['agent_id']} {event['category']} {event['message']}"
        for event in problem_events[:20]
    ]
    context_evidence = [
        f"{event['timestamp']} {event['agent_id']} {event['severity']} {event['category']}: {event['message']}"
        for event in events[:40]
    ]

    if not problem_events:
        return {
            "website_id": website_id,
            "mode": "mock",
            "agents_checked": agents,
            "summary": f"No problem evidence found for {website_id}.",
            "root_cause": "No problem evidence found.",
            "recommended_action": "No action required from current evidence.",
            "confidence": 0.0,
            "evidence": [],
            "context_evidence": context_evidence,
            "fingerprints": [],
            "analysis_window_minutes": window_minutes,
            "context_event_count": len(events),
            "memory_status": "none",
            "memory_matches": [],
            "topology_hints": topology_hints,
        }

    root_cause, recommended_action, confidence = _infer_root_cause(problem_events, categories)
    top_category, count = categories.most_common(1)[0]
    summary = (
        f"{website_id}: found {len(problem_events)} non-normal event(s). "
        f"Top signal is {top_category} x{count}. "
        f"Checked agents: {', '.join(agents)}. "
        f"Root cause: {root_cause}"
    )
    if memory_matches:
        summary += f" Known pattern matched: {memory_matches[0]['root_cause']}"

    return {
        "website_id": website_id,
        "mode": "mock",
        "agents_checked": agents,
        "summary": summary,
        "root_cause": root_cause,
        "recommended_action": recommended_action,
        "confidence": confidence,
        "evidence": evidence,
        "context_evidence": context_evidence,
        "fingerprints": fingerprints,
        "analysis_window_minutes": window_minutes,
        "context_event_count": len(events),
        "memory_status": "matched" if memory_matches else "new",
        "memory_matches": memory_matches,
        "topology_hints": topology_hints,
    }


def _infer_root_cause(
    problem_events: list[dict[str, Any]],
    categories: Counter,
) -> tuple[str, str, float]:
    db_events = [event for event in problem_events if event["category"] == "db_too_many_connections"]
    timeout_events = [
        event
        for event in problem_events
        if event["category"] in {"upstream_timeout", "timeout", "connection_refused"}
    ]
    critical_events = [event for event in problem_events if event["severity"] == "critical"]

    if db_events and timeout_events:
        db_agents = ", ".join(sorted({event["agent_id"] for event in db_events}))
        web_agents = ", ".join(sorted({event["agent_id"] for event in timeout_events}))
        return (
            f"{db_agents} reported too many connections, then {web_agents} reported upstream timeout.",
            "Check database connection limits, slow queries, and app connection pool settings before restarting web workers.",
            0.84,
        )
    if db_events:
        db_agents = ", ".join(sorted({event["agent_id"] for event in db_events}))
        return (
            f"{db_agents} reported too many connections.",
            "Check DB max connections, connection leaks, slow queries, and pool sizing.",
            0.76,
        )
    if critical_events:
        agents = ", ".join(sorted({event["agent_id"] for event in critical_events}))
        top_category = Counter(event["category"] for event in critical_events).most_common(1)[0][0]
        return (
            f"{agents} reported critical {top_category}.",
            "Check host resources first, then restart only the affected service if resources are stable.",
            0.8,
        )
    top_category, _count = categories.most_common(1)[0]
    agents = ", ".join(sorted({event["agent_id"] for event in problem_events if event["category"] == top_category}))
    return (
        f"{agents} reported repeated {top_category}.",
        "Review the affected service logs around the same timestamp and compare with upstream/downstream agents in this website.",
        0.65,
    )


def _remember_pattern(
    store: Store,
    report: dict[str, Any],
    problem_events: list[dict[str, Any]],
    settings: dict[str, Any],
    had_memory_match: bool,
) -> None:
    learning = settings.get("learning", {})
    if not learning.get("enabled", True) or not learning.get("remember_patterns", True):
        report["memory_status"] = "disabled"
        return
    if not problem_events:
        return

    categories = Counter(event["category"] for event in problem_events)
    top_category, _count = categories.most_common(1)[0]
    primary = next(event for event in problem_events if event["category"] == top_category)
    observed_at = str(primary.get("timestamp") or datetime.now(timezone.utc).isoformat())
    memory = store.upsert_incident_memory(
        {
            "website_id": report["website_id"],
            "fingerprint": primary["fingerprint"],
            "category": top_category,
            "root_cause": report["root_cause"],
            "suggested_action": report["recommended_action"],
            "observed_at": observed_at,
            "confidence": report["confidence"],
        }
    )
    if had_memory_match:
        report["memory_status"] = "matched"
        return
    report["memory_status"] = "stored"
    report["memory_matches"] = [memory]


def _context_since(store: Store, website_id: str, window_minutes: int) -> str | None:
    if window_minutes <= 0:
        return None
    latest_events = store.website_context(website_id, limit=1)
    if not latest_events:
        return None
    try:
        anchor = datetime.fromisoformat(str(latest_events[0]["timestamp"]).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (anchor - timedelta(minutes=window_minutes)).astimezone(timezone.utc).isoformat()


def _build_prompt(
    website_id: str,
    events: list[dict[str, Any]],
    problem_events: list[dict[str, Any]],
    memory_matches: list[dict[str, Any]],
    topology_hints: list[dict[str, Any]],
    window_minutes: int,
    settings: dict[str, Any] | None = None,
    er_graph: dict[str, Any] | None = None,
    cascading_timeline: list[dict[str, Any]] | None = None,
) -> str:
    problem_lines = "\n".join(
        f"- {event['timestamp']} {event['agent_id']} {event['agent_role']} {event['category']}: "
        f"{redact_text(str(event['message']), settings)}"
        for event in problem_events[:40]
    )
    context_lines = "\n".join(
        f"- {event['timestamp']} {event['agent_id']} {event['agent_role']} {event['severity']} {event['category']}: "
        f"{redact_text(str(event['message']), settings)}"
        for event in events[:60]
    )
    memory_lines = "\n".join(
        f"- {item['category']}: {item['root_cause']} | action: {item['suggested_action']}"
        for item in memory_matches[:5]
    )
    topology_lines = "\n".join(
        f"- {item['agent_id']} -> {item['target']} ({item['hint_type']}, confidence {float(item.get('confidence') or 0):.2f})"
        for item in topology_hints[:20]
    )
    cascading_lines = "\n".join(
        f"- Step {step.get('step')}: {step.get('title')} — {step.get('detail')}"
        for step in (cascading_timeline or [])
    )
    return (
        "You are an on-prem log incident analyst. Analyze only the supplied website scope.\n"
        f"Website: {website_id}\n"
        f"Analysis window: last {window_minutes} minute(s) from the latest website signal.\n"
        "Analyze the first machine in the evidence first. Expand to later machines only when the supplied evidence shows a dependency. "
        "Return a short Thai report with root cause, affected machines, and next checks.\n"
        "Problem events:\n"
        f"{problem_lines}\n"
        "All website context events in the window:\n"
        f"{context_lines}\n"
        "Topology hints:\n"
        f"{topology_lines or '- none'}\n"
        "Cascading ER timeline:\n"
        f"{cascading_lines or '- none'}\n"
        "Known matching patterns:\n"
        f"{memory_lines or '- none'}"
    )


def _call_configured_ai(
    settings: dict[str, Any],
    prompt: str,
    http_post: HttpPost | None = None,
) -> str:
    mode = str(settings.get("ai", {}).get("mode") or "mock").lower()
    timeout = int(settings.get("limits", {}).get("timeout_seconds") or 45)
    post = http_post or _http_post_json
    try:
        if mode in {"ollama", "local"}:
            provider = settings.get("providers", {}).get("ollama", {})
            api_prov = settings.get("providers", {}).get("api", {})
            url = str(api_prov.get("endpoint") or provider.get("url") or "http://127.0.0.1:11434/api/generate").strip()
            model = str(settings.get("ai", {}).get("model") or provider.get("model") or "llama3.2:3b")
            response = post(url, {}, {"model": model, "prompt": prompt, "stream": False}, timeout)
            return str(response.get("response") or "").strip()
        if mode == "api":
            provider = settings.get("providers", {}).get("api", {})
            endpoint = str(provider.get("endpoint") or "").strip()
            api_key = str(provider.get("api_key") or "").strip()
            model = str(settings.get("ai", {}).get("model") or provider.get("model") or "").strip()
            if not endpoint or not api_key or not model:
                return ""
            response = post(
                endpoint,
                {"Authorization": f"Bearer {api_key}"},
                {"model": model, "messages": [{"role": "user", "content": prompt}]},
                timeout,
            )
            return str(response.get("choices", [{}])[0].get("message", {}).get("content") or "").strip()
    except Exception:
        return ""
    return ""


def _deep_copy(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value))
