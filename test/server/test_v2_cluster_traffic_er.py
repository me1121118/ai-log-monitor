from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest

from server.app.app import create_app


class V2ClusterTrafficErTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = TemporaryDirectory()
        self.data_dir = Path(self.temp.name)
        self.sent_webhooks: list[tuple[str, dict]] = []

        def fake_post(url: str, headers: dict, payload: dict, timeout: int) -> dict:
            self.sent_webhooks.append((url, payload))
            return {"ok": True}

        self.app = create_app(
            self.data_dir,
            enroll_token="secret-enroll",
            admin_token="secret-admin",
            notification_post=fake_post,
        )
        self.admin_headers = {"X-Admin-Token": "secret-admin"}

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_er_cluster_quorum_and_cascading_rca(self) -> None:
        # 1. Create MariaDB 3-Node HA Cluster
        status, _, body = self.app.handle_json(
            "POST",
            "/api/clusters",
            self.admin_headers,
            json.dumps(
                {
                    "cluster_id": "c_mariadb_ha",
                    "website_id": "website_1",
                    "name": "MariaDB Galera HA Cluster",
                    "cluster_type": "galera",
                    "quorum_min": 2,
                }
            ).encode("utf-8"),
        )
        self.assertEqual(status, 201)

        # 2. Register 3 DB nodes (163, 164, 165) and 1 LB node (159)
        now = datetime.now(timezone.utc)
        for idx, ip in [(1, "10.1.15.163"), (2, "10.1.15.164"), (3, "10.1.15.165")]:
            st, _, _ = self.app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "secret-enroll"},
                json.dumps(
                    {
                        "agent_id": f"db{idx}",
                        "website_id": "website_1",
                        "agent_role": "db",
                        "cluster_id": "c_mariadb_ha",
                        "hostname": f"mariabackup-16{idx + 2}.kdt.in.th",
                        "source_ip": ip,
                        "cpu_percent": 15.0 + idx,
                        "ram_percent": 45.0 + idx,
                        "disk_percent": 60.0,
                        "registered_at": now.isoformat(),
                    }
                ).encode("utf-8"),
            )
            self.assertEqual(st, 201)

        self.app.handle_json(
            "POST",
            "/api/agents/register",
            {"X-Enroll-Token": "secret-enroll"},
            json.dumps(
                {
                    "agent_id": "lb1",
                    "website_id": "website_1",
                    "agent_role": "lb",
                    "hostname": "haproxy-1-ceph-159",
                    "source_ip": "10.1.15.159",
                    "registered_at": now.isoformat(),
                }
            ).encode("utf-8"),
        )

        # 3. Add manual ROUTE_TO relation from lb1 -> db1
        st, _, _ = self.app.handle_json(
            "POST",
            "/api/relations",
            self.admin_headers,
            json.dumps(
                {
                    "website_id": "website_1",
                    "source_id": "lb1",
                    "target_id": "db1",
                    "relation_type": "ROUTE_TO",
                    "port": 3306,
                    "protocol": "mysql",
                }
            ).encode("utf-8"),
        )
        self.assertEqual(st, 201)

        # 4. Verify ER Topology Graph reports 3/3 Healthy Quorum
        st, _, graph_bytes = self.app.handle_json(
            "GET",
            "/api/topology-graph?website_id=website_1",
            self.admin_headers,
            b"",
        )
        self.assertEqual(st, 200)
        graph = json.loads(graph_bytes.decode("utf-8"))
        ha_cluster = next(c for c in graph["clusters"] if c["cluster_id"] == "c_mariadb_ha")
        self.assertEqual(ha_cluster["total_nodes"], 3)
        self.assertEqual(ha_cluster["healthy_nodes"], 3)
        self.assertEqual(ha_cluster["quorum_status"], "healthy")

        # 5. Simulate db2 failing with OOM / Too many connections and check Cascading RCA
        self.app.handle_json(
            "POST",
            "/api/ingest",
            {},
            json.dumps(
                {
                    "website_id": "website_1",
                    "agent_id": "db2",
                    "agent_role": "db",
                    "log_type": "mariadb_error",
                    "service": "mariadb",
                    "timestamp": now.isoformat(),
                    "message": "ERROR 1040 (08004): Too many connections on db2",
                }
            ).encode("utf-8"),
        )
        st, _, report_bytes = self.app.handle_json(
            "GET",
            "/api/analyze?website_id=website_1",
            self.admin_headers,
            b"",
        )
        self.assertEqual(st, 200)
        report = json.loads(report_bytes.decode("utf-8"))
        self.assertIn("er_topology", report)
        self.assertIn("cascading_timeline", report)
        self.assertTrue(len(report["cascading_timeline"]) >= 1)
        self.assertIn("thai_summary", report)
        # Verify sibling cluster nodes db1 and db3 were traced via PEER_SYNC
        self.assertIn("db1", report["analysis_sequence"])
        self.assertIn("db3", report["analysis_sequence"])

        # 6. Verify Rolling SQLite daily log file was created
        st, _, daily_bytes = self.app.handle_json(
            "GET",
            "/api/storage/daily",
            self.admin_headers,
            b"",
        )
        self.assertEqual(st, 200)
        daily_files = json.loads(daily_bytes.decode("utf-8"))["files"]
        self.assertTrue(len(daily_files) >= 1)

    def test_traffic_anomaly_detection_and_batch_ingest(self) -> None:
        now = datetime.now(timezone.utc)
        batch_events = []
        # Simulate 20 rapid brute-force 401 requests from a single attacker IP
        for i in range(20):
            batch_events.append(
                {
                    "website_id": "website_1",
                    "agent_id": "lb1",
                    "agent_role": "lb",
                    "log_type": "nginx_access",
                    "service": "nginx",
                    "timestamp": (now + timedelta(milliseconds=i * 50)).isoformat(),
                    "status_code": 401,
                    "message": f'185.220.101.42 - - [05/Nov/2026:12:00:00 +0000] "POST /api/v1/login HTTP/1.1" 401 128',
                    "metadata": {
                        "client_ip": "185.220.101.42",
                        "method": "POST",
                        "path": "/api/v1/login",
                        "status_code": 401,
                    },
                }
            )

        st, _, resp_bytes = self.app.handle_json(
            "POST",
            "/api/ingest/batch",
            {},
            json.dumps({"events": batch_events}).encode("utf-8"),
        )
        self.assertEqual(st, 201)
        resp = json.loads(resp_bytes.decode("utf-8"))
        self.assertEqual(resp["ingested"], 20)
        self.assertTrue(len(resp.get("traffic_anomalies", [])) >= 1)

        # Verify /api/traffic summary reflects the requests and brute_force anomaly
        st, _, traffic_bytes = self.app.handle_json(
            "GET",
            "/api/traffic?website_id=website_1",
            self.admin_headers,
            b"",
        )
        self.assertEqual(st, 200)
        traffic = json.loads(traffic_bytes.decode("utf-8"))
        self.assertEqual(traffic["requests_1m"], 20)
        self.assertEqual(traffic["status_counts"]["4xx"], 20)
        anomaly_types = {a["anomaly_type"] for a in traffic["recent_anomalies"]}
        self.assertIn("brute_force", anomaly_types)


if __name__ == "__main__":
    unittest.main()
