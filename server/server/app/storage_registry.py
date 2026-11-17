from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def _opt_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _opt_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _parse_iso_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


AGENT_SELECT_COLUMNS = """
    agent_id, website_id, agent_role, hostname, source_ip, machine_id,
    status, registered_at, last_seen_at, cluster_id,
    cpu_percent, ram_percent, disk_percent, maintenance_until
"""


class RegistryStoreMixin:
    def register_agent(self, agent: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(agent.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("missing required agent field: agent_id")
        agent_role = str(agent.get("agent_role") or agent.get("role") or "unknown")
        registered_at = str(agent.get("registered_at") or "")
        if not registered_at:
            raise ValueError("missing required agent field: registered_at")
        token = "agt_" + agent_id + "_" + str(abs(hash((agent_id, registered_at))))[:16]
        incoming_website_id = str(agent.get("website_id") or "").strip() or None
        machine_id = str(agent.get("machine_id") or "").strip() or None
        cluster_id = str(agent.get("cluster_id") or "").strip() or None
        cpu_percent = _opt_float(agent.get("cpu_percent"))
        ram_percent = _opt_float(agent.get("ram_percent"))
        disk_percent = _opt_float(agent.get("disk_percent"))
        maintenance_until = str(agent.get("maintenance_until") or "").strip() or None
        final_website_id = incoming_website_id

        with self._connect() as db:
            if machine_id:
                duplicate = db.execute(
                    "select agent_id from agents where machine_id = ? and agent_id != ?",
                    (machine_id, agent_id),
                ).fetchone()
                if duplicate:
                    raise ValueError(
                        f"machine is already registered as agent_id: {duplicate['agent_id']}"
                    )
            existing = db.execute(
                "select * from agents where agent_id = ?",
                (agent_id,),
            ).fetchone()
            if existing:
                token = str(existing["agent_token"])
                final_website_id = incoming_website_id or existing["website_id"]
                db.execute(
                    """
                    update agents
                    set website_id = coalesce(?, website_id),
                        agent_role = ?,
                        hostname = coalesce(?, hostname),
                        source_ip = coalesce(?, source_ip),
                        machine_id = coalesce(?, machine_id),
                        cluster_id = coalesce(?, cluster_id),
                        cpu_percent = coalesce(?, cpu_percent),
                        ram_percent = coalesce(?, ram_percent),
                        disk_percent = coalesce(?, disk_percent),
                        maintenance_until = coalesce(?, maintenance_until),
                        status = 'active',
                        last_seen_at = ?
                    where agent_id = ?
                    """,
                    (
                        incoming_website_id,
                        agent_role,
                        agent.get("hostname"),
                        agent.get("source_ip"),
                        machine_id,
                        cluster_id,
                        cpu_percent,
                        ram_percent,
                        disk_percent,
                        maintenance_until,
                        registered_at,
                        agent_id,
                    ),
                )
            else:
                db.execute(
                    """
                    insert into agents (
                        agent_id, website_id, agent_role, hostname, source_ip, machine_id, status,
                        agent_token, registered_at, last_seen_at, cluster_id,
                        cpu_percent, ram_percent, disk_percent, maintenance_until
                    ) values (?, ?, ?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        incoming_website_id,
                        agent_role,
                        agent.get("hostname"),
                        agent.get("source_ip"),
                        machine_id,
                        token,
                        registered_at,
                        registered_at,
                        cluster_id,
                        cpu_percent,
                        ram_percent,
                        disk_percent,
                        maintenance_until,
                    ),
                )
            row = db.execute(
                f"select {AGENT_SELECT_COLUMNS} from agents where agent_id = ?",
                (agent_id,),
            ).fetchone()

        result = dict(row) if row else {}
        result.update(
            {
                "agent_id": agent_id,
                "website_id": final_website_id,
                "agent_role": agent_role,
                "agent_token": token,
                "status": "active",
            }
        )
        return result

    def upsert_website(self, website: dict[str, Any]) -> dict[str, Any]:
        website_id = str(website.get("website_id") or "").strip()
        if not website_id:
            raise ValueError("missing required website field: website_id")
        name = str(website.get("name") or website_id)
        created_at = str(website.get("created_at") or "")
        if not created_at:
            raise ValueError("missing required website field: created_at")

        with self._connect() as db:
            db.execute(
                """
                insert into websites (website_id, name, status, created_at)
                values (?, ?, 'active', ?)
                on conflict(website_id) do update set
                    name = excluded.name,
                    status = 'active'
                """,
                (website_id, name, created_at),
            )
        return {"website_id": website_id, "name": name, "status": "active"}

    def list_websites(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                "select * from websites order by website_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def list_agents(self) -> list[dict[str, Any]]:
        with self._connect() as db:
            rows = db.execute(
                f"""
                select {AGENT_SELECT_COLUMNS}
                from agents
                order by agent_id
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def update_agent_heartbeat(self, heartbeat: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(heartbeat.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("missing required heartbeat field: agent_id")
        observed_at = str(heartbeat.get("observed_at") or "").strip()
        if not observed_at:
            raise ValueError("missing required heartbeat field: observed_at")
        status = str(heartbeat.get("status") or "active").strip() or "active"
        website_id = str(heartbeat.get("website_id") or "").strip() or None
        agent_role = str(heartbeat.get("agent_role") or heartbeat.get("role") or "").strip() or None
        cluster_id = str(heartbeat.get("cluster_id") or "").strip() or None
        cpu_percent = _opt_float(heartbeat.get("cpu_percent"))
        ram_percent = _opt_float(heartbeat.get("ram_percent"))
        disk_percent = _opt_float(heartbeat.get("disk_percent"))
        maintenance_until = (
            str(heartbeat.get("maintenance_until") or "").strip() or None
            if "maintenance_until" in heartbeat
            else None
        )

        with self._connect() as db:
            cursor = db.execute(
                """
                update agents
                set status = ?,
                    last_seen_at = ?,
                    website_id = coalesce(?, website_id),
                    agent_role = coalesce(?, agent_role),
                    hostname = coalesce(?, hostname),
                    source_ip = coalesce(?, source_ip),
                    machine_id = coalesce(?, machine_id),
                    cluster_id = coalesce(?, cluster_id),
                    cpu_percent = coalesce(?, cpu_percent),
                    ram_percent = coalesce(?, ram_percent),
                    disk_percent = coalesce(?, disk_percent),
                    maintenance_until = coalesce(?, maintenance_until)
                where agent_id = ?
                """,
                (
                    status,
                    observed_at,
                    website_id,
                    agent_role,
                    heartbeat.get("hostname"),
                    heartbeat.get("source_ip"),
                    heartbeat.get("machine_id"),
                    cluster_id,
                    cpu_percent,
                    ram_percent,
                    disk_percent,
                    maintenance_until,
                    agent_id,
                ),
            )
            if cursor.rowcount <= 0:
                raise ValueError(f"agent not found: {agent_id}")
            row = db.execute(
                f"""
                select {AGENT_SELECT_COLUMNS}
                from agents
                where agent_id = ?
                """,
                (agent_id,),
            ).fetchone()
        return dict(row)

    def assign_agent(self, assignment: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(assignment.get("agent_id") or "").strip()
        website_id = str(assignment.get("website_id") or "").strip()
        agent_role = str(assignment.get("agent_role") or assignment.get("role") or "").strip()
        if not agent_id:
            raise ValueError("missing required assignment field: agent_id")
        if not website_id:
            raise ValueError("missing required assignment field: website_id")

        has_cluster_key = "cluster_id" in assignment
        incoming_cluster_id = str(assignment.get("cluster_id") or "").strip() or None
        incoming_hostname = str(assignment.get("hostname") or "").strip() or None
        upsert_if_missing = bool(assignment.get("upsert_if_missing"))

        with self._connect() as db:
            existing = db.execute(
                "select * from agents where agent_id = ?",
                (agent_id,),
            ).fetchone()
            if not existing:
                if not upsert_if_missing:
                    raise ValueError(f"agent not found: {agent_id}")
                now_iso = datetime.now(timezone.utc).isoformat()
                db.execute(
                    """
                    insert into agents (
                        agent_id, website_id, agent_role, token, status,
                        registered_at, last_seen_at, hostname, cluster_id
                    ) values (?, ?, ?, ?, 'active', ?, ?, ?, ?)
                    """,
                    (
                        agent_id,
                        website_id,
                        agent_role or "app",
                        "manual_ui_token",
                        now_iso,
                        now_iso,
                        incoming_hostname or agent_id,
                        incoming_cluster_id,
                    ),
                )
            else:
                final_role = agent_role or str(existing["agent_role"])
                final_cluster_id = incoming_cluster_id if has_cluster_key else existing["cluster_id"]
                final_hostname = incoming_hostname if incoming_hostname is not None else existing["hostname"]
                db.execute(
                    """
                    update agents
                    set website_id = ?, agent_role = ?, cluster_id = ?, hostname = ?
                    where agent_id = ?
                    """,
                    (website_id, final_role, final_cluster_id, final_hostname, agent_id),
                )
            row = db.execute(
                f"select {AGENT_SELECT_COLUMNS} from agents where agent_id = ?",
                (agent_id,),
            ).fetchone()
        return dict(row)

    def delete_agent(self, agent_id: str) -> bool:
        clean_id = str(agent_id or "").strip()
        if not clean_id:
            return False
        with self._connect() as db:
            db.execute("delete from vm_relations where source_id = ? or target_id = ?", (clean_id, clean_id))
            db.execute("delete from log_sources where agent_id = ?", (clean_id,))
            db.execute("delete from topology_hints where agent_id = ? or target = ?", (clean_id, clean_id))
            cursor = db.execute("delete from agents where agent_id = ?", (clean_id,))
        return bool(cursor.rowcount > 0)

    def set_agent_maintenance(self, agent_id: str, maintenance_until: str | None) -> dict[str, Any]:
        clean_agent_id = str(agent_id or "").strip()
        if not clean_agent_id:
            raise ValueError("missing required agent field: agent_id")
        clean_until = str(maintenance_until or "").strip() or None
        with self._connect() as db:
            cursor = db.execute(
                "update agents set maintenance_until = ? where agent_id = ?",
                (clean_until, clean_agent_id),
            )
            if cursor.rowcount <= 0:
                raise ValueError(f"agent not found: {clean_agent_id}")
            row = db.execute(
                f"select {AGENT_SELECT_COLUMNS} from agents where agent_id = ?",
                (clean_agent_id,),
            ).fetchone()
        return dict(row)

    def upsert_cluster(self, cluster: dict[str, Any]) -> dict[str, Any]:
        website_id = str(cluster.get("website_id") or "").strip()
        if not website_id:
            raise ValueError("missing required cluster field: website_id")
        cluster_id = str(cluster.get("cluster_id") or "").strip()
        name = str(cluster.get("name") or cluster_id).strip()
        if not cluster_id:
            if not name:
                raise ValueError("missing required cluster field: cluster_id")
            slug = "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_") or "cluster"
            cluster_id = f"cluster_{website_id}_{slug}"
        if not name:
            name = cluster_id
        cluster_type = str(cluster.get("cluster_type") or "ha_cluster").strip() or "ha_cluster"
        quorum_min = max(int(cluster.get("quorum_min") if cluster.get("quorum_min") is not None else 2), 1)
        status = str(cluster.get("status") or "active").strip() or "active"
        description = str(cluster.get("description") or "").strip()
        created_at = str(cluster.get("created_at") or "").strip() or datetime.now(timezone.utc).isoformat()

        with self._connect() as db:
            db.execute(
                """
                insert into clusters (
                    cluster_id, website_id, name, cluster_type, quorum_min,
                    status, description, created_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(cluster_id) do update set
                    website_id = excluded.website_id,
                    name = excluded.name,
                    cluster_type = excluded.cluster_type,
                    quorum_min = excluded.quorum_min,
                    status = excluded.status,
                    description = excluded.description
                """,
                (
                    cluster_id,
                    website_id,
                    name,
                    cluster_type,
                    quorum_min,
                    status,
                    description,
                    created_at,
                ),
            )
            row = db.execute(
                "select * from clusters where cluster_id = ?",
                (cluster_id,),
            ).fetchone()
        return dict(row)

    def list_clusters(self, website_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from clusters"
        params: list[Any] = []
        if website_id:
            query += " where website_id = ?"
            params.append(website_id)
        query += " order by website_id, cluster_id"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def delete_cluster(self, cluster_id: str) -> bool:
        clean_id = str(cluster_id or "").strip()
        if not clean_id:
            return False
        with self._connect() as db:
            db.execute(
                "update agents set cluster_id = null where cluster_id = ?",
                (clean_id,),
            )
            cursor = db.execute(
                "delete from clusters where cluster_id = ?",
                (clean_id,),
            )
        return bool(cursor.rowcount > 0)

    def upsert_vm_relation(self, rel: dict[str, Any]) -> dict[str, Any]:
        website_id = str(rel.get("website_id") or "").strip()
        source_id = str(rel.get("source_id") or "").strip()
        target_id = str(rel.get("target_id") or "").strip()
        relation_type = str(rel.get("relation_type") or "ROUTE_TO").strip().upper() or "ROUTE_TO"
        if not website_id:
            raise ValueError("missing required vm_relation field: website_id")
        if not source_id:
            raise ValueError("missing required vm_relation field: source_id")
        if not target_id:
            raise ValueError("missing required vm_relation field: target_id")

        relation_id = str(rel.get("relation_id") or "").strip()
        if not relation_id:
            basis = f"{website_id}|{source_id}|{target_id}|{relation_type}"
            relation_id = "rel_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]

        port = _opt_int(rel.get("port"))
        protocol = str(rel.get("protocol") or "").strip()
        is_manual = 1 if bool(rel.get("is_manual", True)) else 0
        confidence = float(rel.get("confidence") if rel.get("confidence") is not None else 1.0)
        last_seen_at = str(rel.get("last_seen_at") or "").strip() or datetime.now(timezone.utc).isoformat()
        metadata_json = json.dumps(dict(rel.get("metadata") or {}), sort_keys=True)

        with self._connect() as db:
            db.execute(
                """
                insert into vm_relations (
                    relation_id, website_id, source_id, target_id, relation_type,
                    port, protocol, is_manual, confidence, last_seen_at, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(relation_id) do update set
                    website_id = excluded.website_id,
                    source_id = excluded.source_id,
                    target_id = excluded.target_id,
                    relation_type = excluded.relation_type,
                    port = excluded.port,
                    protocol = excluded.protocol,
                    is_manual = excluded.is_manual,
                    confidence = excluded.confidence,
                    last_seen_at = excluded.last_seen_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    relation_id,
                    website_id,
                    source_id,
                    target_id,
                    relation_type,
                    port,
                    protocol,
                    is_manual,
                    confidence,
                    last_seen_at,
                    metadata_json,
                ),
            )
            row = db.execute(
                "select * from vm_relations where relation_id = ?",
                (relation_id,),
            ).fetchone()
        return self._vm_relation_row_to_dict(row)

    def list_vm_relations(self, website_id: str | None = None) -> list[dict[str, Any]]:
        query = "select * from vm_relations"
        params: list[Any] = []
        if website_id:
            query += " where website_id = ?"
            params.append(website_id)
        query += " order by website_id, source_id, target_id, relation_type"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._vm_relation_row_to_dict(row) for row in rows]

    def delete_vm_relation(self, relation_id: str) -> bool:
        clean_id = str(relation_id or "").strip()
        if not clean_id:
            return False
        with self._connect() as db:
            cursor = db.execute(
                "delete from vm_relations where relation_id = ?",
                (clean_id,),
            )
        return bool(cursor.rowcount > 0)

    def build_er_topology_graph(
        self,
        website_id: str,
        stale_Grouping_seconds: int = 90,
        **kwargs: Any,
    ) -> dict[str, Any]:
        clean_website_id = str(website_id or "").strip()
        stale_window = int(kwargs.get("stale_seconds") or stale_Grouping_seconds or 90)

        stored_clusters = self.list_clusters(clean_website_id)
        all_agents = [
            agent
            for agent in self.list_agents()
            if str(agent.get("website_id") or "") == clean_website_id
        ]
        explicit_relations = self.list_vm_relations(clean_website_id)
        hints = self.list_topology_hints(clean_website_id)

        parsed_times = [
            dt
            for dt in (_parse_iso_utc(a.get("last_seen_at")) for a in all_agents)
            if dt is not None
        ]
        ref_now = max(parsed_times) if parsed_times else datetime.now(timezone.utc)

        nodes: list[dict[str, Any]] = []
        agent_by_id: dict[str, dict[str, Any]] = {}
        host_ip_lookup: dict[str, str] = {}

        for agent in all_agents:
            aid = str(agent["agent_id"])
            status_val = str(agent.get("status") or "").lower()
            seen_dt = _parse_iso_utc(agent.get("last_seen_at"))
            is_stale = False
            if seen_dt is not None and stale_window > 0:
                age_sec = (ref_now - seen_dt).total_seconds()
                if age_sec > stale_window:
                    is_stale = True
            is_healthy = status_val in {"active", "online", "healthy"} and not is_stale

            maint_until = agent.get("maintenance_until")
            in_maintenance = False
            if maint_until:
                maint_dt = _parse_iso_utc(maint_until)
                if maint_dt is None or maint_dt >= ref_now:
                    in_maintenance = True

            node = {
                **agent,
                "is_stale": is_stale,
                "is_healthy": is_healthy,
                "in_maintenance": in_maintenance,
            }
            nodes.append(node)
            agent_by_id[aid] = node
            host_ip_lookup[aid] = aid
            if agent.get("hostname"):
                host_ip_lookup[str(agent["hostname"])] = aid
            if agent.get("source_ip"):
                host_ip_lookup[str(agent["source_ip"])] = aid

        clusters_by_id: dict[str, dict[str, Any]] = {
            str(c["cluster_id"]): {**c, "is_auto": False} for c in stored_clusters
        }

        unclustered_by_role: dict[str, list[dict[str, Any]]] = {}
        for node in nodes:
            cid = str(node.get("cluster_id") or "").strip()
            if cid:
                if cid not in clusters_by_id:
                    clusters_by_id[cid] = {
                        "cluster_id": cid,
                        "website_id": clean_website_id,
                        "name": cid,
                        "cluster_type": "ha_cluster",
                        "quorum_min": 2,
                        "status": "active",
                        "description": "Implicit cluster from agent assignment",
                        "created_at": node.get("registered_at") or "",
                        "is_auto": True,
                    }
            else:
                role = str(node.get("agent_role") or "unknown").strip() or "unknown"
                unclustered_by_role.setdefault(role, []).append(node)

        for role, role_nodes in sorted(unclustered_by_role.items()):
            if len(role_nodes) >= 2:
                auto_cid = f"cluster_{clean_website_id}_{role}"
                quorum_min = (len(role_nodes) // 2) + 1
                if auto_cid not in clusters_by_id:
                    clusters_by_id[auto_cid] = {
                        "cluster_id": auto_cid,
                        "website_id": clean_website_id,
                        "name": f"{role.upper()} HA Cluster",
                        "cluster_type": "ha_cluster",
                        "quorum_min": quorum_min,
                        "status": "active",
                        "description": f"Auto-grouped {role} cluster",
                        "created_at": role_nodes[0].get("registered_at") or "",
                        "is_auto": True,
                    }
                for node in role_nodes:
                    node["cluster_id"] = auto_cid

        cluster_list: list[dict[str, Any]] = []
        for cid, cluster in sorted(clusters_by_id.items()):
            members = [n for n in nodes if str(n.get("cluster_id") or "") == cid]
            total_nodes = len(members)
            healthy_nodes = sum(1 for n in members if n["is_healthy"])
            quorum_min = int(cluster.get("quorum_min") or 2)
            if total_nodes == 0:
                quorum_status = "empty"
            elif healthy_nodes == total_nodes:
                quorum_status = "healthy"
            elif healthy_nodes >= quorum_min:
                quorum_status = "degraded"
            else:
                quorum_status = "quorum_lost"

            cluster_list.append(
                {
                    **cluster,
                    "member_ids": [n["agent_id"] for n in members],
                    "total_nodes": total_nodes,
                    "healthy_nodes": healthy_nodes,
                    "quorum_min": quorum_min,
                    "quorum_status": quorum_status,
                }
            )

        relations: list[dict[str, Any]] = []
        seen_edges: set[tuple[str, str, str]] = set()

        for rel in explicit_relations:
            key = (str(rel["source_id"]), str(rel["target_id"]), str(rel["relation_type"]))
            seen_edges.add(key)
            relations.append(rel)

        hint_type_map = {
            "http_upstream": "ROUTE_TO",
            "database": "ROUTE_TO",
            "peer_sync": "PEER_SYNC",
            "replicate": "REPLICATE",
            "mount": "MOUNT",
        }
        for hint in hints:
            src_id = str(hint["agent_id"])
            raw_target = str(hint["target"])
            host_part = raw_target.split(":")[0].strip()
            port_part = _opt_int(raw_target.split(":")[1]) if ":" in raw_target else None
            target_id = host_ip_lookup.get(raw_target) or host_ip_lookup.get(host_part) or raw_target
            rel_type = hint_type_map.get(str(hint.get("hint_type") or "").lower(), "ROUTE_TO")
            key = (src_id, target_id, rel_type)
            if key in seen_edges or src_id == target_id:
                continue
            seen_edges.add(key)
            basis = f"{clean_website_id}|{src_id}|{target_id}|{rel_type}"
            relations.append(
                {
                    "relation_id": "rel_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16],
                    "website_id": clean_website_id,
                    "source_id": src_id,
                    "target_id": target_id,
                    "relation_type": rel_type,
                    "port": port_part,
                    "protocol": str(hint.get("hint_type") or ""),
                    "is_manual": False,
                    "confidence": float(hint.get("confidence") or 0.7),
                    "last_seen_at": str(hint.get("last_seen_at") or ""),
                    "metadata": dict(hint.get("metadata") or {}),
                }
            )

        for cluster in cluster_list:
            member_ids = list(cluster.get("member_ids") or [])
            if len(member_ids) < 2:
                continue
            member_set = set(member_ids)
            has_peer_edges = any(
                r["source_id"] in member_set
                and r["target_id"] in member_set
                and r["relation_type"] in {"PEER_SYNC", "REPLICATE"}
                for r in relations
            )
            if not has_peer_edges:
                for idx in range(len(member_ids)):
                    for jdx in range(idx + 1, len(member_ids)):
                        src_id = member_ids[idx]
                        dst_id = member_ids[jdx]
                        key = (src_id, dst_id, "PEER_SYNC")
                        if key in seen_edges:
                            continue
                        seen_edges.add(key)
                        basis = f"{clean_website_id}|{src_id}|{dst_id}|PEER_SYNC"
                        relations.append(
                            {
                                "relation_id": "rel_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16],
                                "website_id": clean_website_id,
                                "source_id": src_id,
                                "target_id": dst_id,
                                "relation_type": "PEER_SYNC",
                                "port": None,
                                "protocol": "cluster_mesh",
                                "is_manual": False,
                                "confidence": 0.9,
                                "last_seen_at": "",
                                "metadata": {"cluster_id": cluster["cluster_id"]},
                            }
                        )

        summary = {
            "total_clusters": len(cluster_list),
            "total_nodes": len(nodes),
            "healthy_nodes": sum(1 for n in nodes if n["is_healthy"]),
            "degraded_clusters": sum(1 for c in cluster_list if c["quorum_status"] == "degraded"),
            "quorum_lost_clusters": sum(1 for c in cluster_list if c["quorum_status"] == "quorum_lost"),
        }

        return {
            "website_id": clean_website_id,
            "clusters": cluster_list,
            "nodes": nodes,
            "relations": relations,
            "summary": summary,
        }

    def upsert_log_source(self, source: dict[str, Any]) -> dict[str, Any]:
        source_id = str(source.get("source_id") or "").strip()
        website_id = str(source.get("website_id") or "").strip()
        agent_id = str(source.get("agent_id") or "").strip()
        path = str(source.get("path") or "").strip()
        if not source_id:
            raise ValueError("missing required log source field: source_id")
        if not website_id:
            raise ValueError("missing required log source field: website_id")
        if not agent_id:
            raise ValueError("missing required log source field: agent_id")
        if not path:
            raise ValueError("missing required log source field: path")

        name = str(source.get("name") or source_id)
        source_type = str(source.get("source_type") or source.get("type") or "candidate")
        service = str(source.get("service") or source_type)
        classification = str(source.get("classification") or source_type)
        confidence = float(source.get("confidence") or 0.0)
        status = str(source.get("status") or "unknown")
        last_seen_at = str(source.get("last_seen_at") or "")
        if not last_seen_at:
            raise ValueError("missing required log source field: last_seen_at")
        metadata_json = json.dumps(dict(source.get("metadata") or {}), sort_keys=True)

        with self._connect() as db:
            existing = db.execute(
                "select first_seen_at from log_sources where source_id = ?",
                (source_id,),
            ).fetchone()
            first_seen_at = str(existing["first_seen_at"]) if existing else last_seen_at
            db.execute(
                """
                insert into log_sources (
                    source_id, website_id, agent_id, name, path, source_type, service,
                    classification, confidence, status, first_seen_at, last_seen_at,
                    metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(source_id) do update set
                    website_id = excluded.website_id,
                    agent_id = excluded.agent_id,
                    name = excluded.name,
                    path = excluded.path,
                    source_type = excluded.source_type,
                    service = excluded.service,
                    classification = excluded.classification,
                    confidence = excluded.confidence,
                    status = excluded.status,
                    last_seen_at = excluded.last_seen_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    source_id,
                    website_id,
                    agent_id,
                    name,
                    path,
                    source_type,
                    service,
                    classification,
                    confidence,
                    status,
                    first_seen_at,
                    last_seen_at,
                    metadata_json,
                ),
            )
        return self._log_source_by_id(source_id)

    def list_log_sources(
        self,
        website_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "select * from log_sources"
        clauses: list[str] = []
        params: list[Any] = []
        if website_id:
            clauses.append("website_id = ?")
            params.append(website_id)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by website_id, agent_id, name"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._log_source_row_to_dict(row) for row in rows]

    def replace_agent_log_sources(
        self,
        website_id: str,
        agent_id: str,
        sources: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Replace one agent's inventory so removed config entries do not linger."""
        stored = [self.upsert_log_source(source) for source in sources]
        source_ids = [str(source["source_id"]) for source in stored]
        with self._connect() as db:
            if source_ids:
                placeholders = ",".join("?" for _ in source_ids)
                db.execute(
                    f"delete from log_sources where website_id = ? and agent_id = ? "
                    f"and source_id not in ({placeholders})",
                    [website_id, agent_id, *source_ids],
                )
            else:
                db.execute(
                    "delete from log_sources where website_id = ? and agent_id = ?",
                    (website_id, agent_id),
                )
        return stored

    def upsert_topology_hint(self, hint: dict[str, Any]) -> dict[str, Any]:
        website_id = str(hint.get("website_id") or "").strip()
        agent_id = str(hint.get("agent_id") or "").strip()
        source = str(hint.get("source") or "").strip()
        hint_type = str(hint.get("hint_type") or hint.get("type") or "").strip()
        target = str(hint.get("target") or "").strip()
        if not website_id:
            raise ValueError("missing required topology hint field: website_id")
        if not agent_id:
            raise ValueError("missing required topology hint field: agent_id")
        if not source:
            raise ValueError("missing required topology hint field: source")
        if not hint_type:
            raise ValueError("missing required topology hint field: hint_type")
        if not target:
            raise ValueError("missing required topology hint field: target")

        hint_id = str(hint.get("hint_id") or "").strip()
        if not hint_id:
            basis = f"{website_id}|{agent_id}|{source}|{hint_type}|{target}"
            hint_id = "topo_" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:20]
        confidence = float(hint.get("confidence") or 0.0)
        last_seen_at = str(hint.get("last_seen_at") or "")
        if not last_seen_at:
            raise ValueError("missing required topology hint field: last_seen_at")
        metadata_json = json.dumps(dict(hint.get("metadata") or {}), sort_keys=True)

        with self._connect() as db:
            existing = db.execute(
                "select first_seen_at from topology_hints where hint_id = ?",
                (hint_id,),
            ).fetchone()
            first_seen_at = str(existing["first_seen_at"]) if existing else last_seen_at
            db.execute(
                """
                insert into topology_hints (
                    hint_id, website_id, agent_id, source, hint_type, target,
                    confidence, first_seen_at, last_seen_at, metadata_json
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                on conflict(hint_id) do update set
                    website_id = excluded.website_id,
                    agent_id = excluded.agent_id,
                    source = excluded.source,
                    hint_type = excluded.hint_type,
                    target = excluded.target,
                    confidence = excluded.confidence,
                    last_seen_at = excluded.last_seen_at,
                    metadata_json = excluded.metadata_json
                """,
                (
                    hint_id,
                    website_id,
                    agent_id,
                    source,
                    hint_type,
                    target,
                    confidence,
                    first_seen_at,
                    last_seen_at,
                    metadata_json,
                ),
            )
        return self._topology_hint_by_id(hint_id)

    def list_topology_hints(
        self,
        website_id: str | None = None,
        agent_id: str | None = None,
    ) -> list[dict[str, Any]]:
        query = "select * from topology_hints"
        clauses: list[str] = []
        params: list[Any] = []
        if website_id:
            clauses.append("website_id = ?")
            params.append(website_id)
        if agent_id:
            clauses.append("agent_id = ?")
            params.append(agent_id)
        if clauses:
            query += " where " + " and ".join(clauses)
        query += " order by website_id, agent_id, hint_type, target"
        with self._connect() as db:
            rows = db.execute(query, params).fetchall()
        return [self._topology_hint_row_to_dict(row) for row in rows]
