import json
import tempfile
import unittest
from pathlib import Path

from server.app.app import create_app


class HttpApiTests(unittest.TestCase):
    def test_agent_register_requires_enroll_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), enroll_token="install-token")
            payload = {
                "agent_id": "web01",
                "agent_role": "web",
                "hostname": "web01.local",
                "source_ip": "10.1.0.21",
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "wrong-token"},
                json.dumps(payload).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 401)
            self.assertEqual(response["error"], "invalid enroll token")

    def test_agent_register_returns_agent_token(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), enroll_token="install-token")
            payload = {
                "agent_id": "web01",
                "agent_role": "web",
                "hostname": "web01.local",
                "source_ip": "10.1.0.21",
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "install-token"},
                json.dumps(payload).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(response["agent_id"], "web01")
            self.assertTrue(response["agent_token"].startswith("agt_"))

    def test_agent_register_auto_creates_website_from_agent_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), enroll_token="install-token")
            payload = {
                "agent_id": "db01",
                "agent_role": "db",
                "website_id": "website_3",
                "website_name": "Website 3",
                "hostname": "db01.local",
                "source_ip": "10.1.0.31",
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "install-token"},
                json.dumps(payload).encode("utf-8"),
            )
            list_status, _list_headers, list_body = app.handle_json("GET", "/api/websites", {}, b"")
            agent_status, _agent_headers, agent_body = app.handle_json("GET", "/api/agents", {}, b"")

            response = json.loads(body.decode("utf-8"))
            websites = json.loads(list_body.decode("utf-8"))["websites"]
            agents = json.loads(agent_body.decode("utf-8"))["agents"]
            self.assertEqual(status, 201)
            self.assertEqual(response["website_id"], "website_3")
            self.assertEqual(list_status, 200)
            self.assertEqual(websites[0]["website_id"], "website_3")
            self.assertEqual(websites[0]["name"], "Website 3")
            self.assertEqual(agent_status, 200)
            self.assertEqual(agents[0]["website_id"], "website_3")

    def test_ingest_endpoint_returns_incident_for_problem_log(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            payload = {
                "website_id": "website_1",
                "agent_id": "web01",
                "agent_role": "web",
                "timestamp": "2026-07-14T10:32:11+07:00",
                "status_code": 502,
                "message": "upstream timed out while reading response header from upstream",
            }

            status, headers, body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(payload).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(response["severity"], "problem")
            self.assertIsNotNone(response["incident_id"])

    def test_normal_ingest_is_buffered_without_persistent_storage(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            app = create_app(data_dir)
            payload = {
                "website_id": "website_1",
                "agent_id": "web01",
                "agent_role": "web",
                "source_id": "src_nginx_access",
                "file_path": "/host/var/log/nginx/access.log",
                "timestamp": "2026-07-14T10:32:11+07:00",
                "status_code": 200,
                "message": "GET /health HTTP/1.1 200",
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(payload).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 202)
            self.assertTrue(response["buffered"])
            self.assertEqual(response["severity"], "normal")
            self.assertEqual(app.store.count_events("website_1"), 0)
            self.assertFalse((data_dir / "raw_logs").exists())

    def test_problem_ingest_persists_same_source_buffer_as_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            common = {
                "website_id": "website_1",
                "agent_id": "db1",
                "agent_role": "db",
                "source_id": "src_mariadb_error",
                "file_path": "/host/var/log/mysql/error.log",
                "timestamp": "2026-07-30T10:00:00+00:00",
            }
            app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps({**common, "message": "ready for connections"}).encode("utf-8"),
            )

            status, _headers, _body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps({**common, "message": "too many connections"}).encode("utf-8"),
            )

            events = app.store.recent_events()
            self.assertEqual(status, 201)
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["severity"], "problem")
            self.assertEqual(events[0]["metadata"]["context_before"][0]["message"], "ready for connections")

            report_status, _report_headers, report_body = app.handle_json(
                "GET", "/api/analyze?website_id=website_1", {}, b""
            )
            report = json.loads(report_body.decode("utf-8"))
            self.assertEqual(report_status, 200)
            self.assertTrue(any("ready for connections" in line for line in report["context_evidence"]))

    def test_ingest_endpoint_writes_per_source_raw_archive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            app = create_app(data_dir)
            payload = {
                "website_id": "website_1",
                "agent_id": "db1",
                "agent_role": "db",
                "log_type": "syslog",
                "service": "system",
                "source_id": "src_syslog123456",
                "file_path": "/host/var/log/syslog",
                "timestamp": "2026-07-17T00:01:02+00:00",
                "message": "critical error disk full",
                "event_uid": "uid-raw-archive",
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(payload).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            files = list((data_dir / "raw_logs" / "website_1" / "db1").glob("*/*.jsonl"))
            self.assertEqual(status, 201)
            self.assertEqual(response["severity"], "critical")
            self.assertEqual(len(files), 1)
            self.assertEqual(files[0].name, "2026-07-17.jsonl")
            row = json.loads(files[0].read_text(encoding="utf-8").splitlines()[0])
            self.assertEqual(row["event_id"], response["event_id"])
            self.assertEqual(row["source_id"], "src_syslog123456")
            self.assertEqual(row["file_path"], "/host/var/log/syslog")
            self.assertEqual(row["message"], "critical error disk full")

    def test_duplicate_ingest_does_not_append_duplicate_raw_archive_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            app = create_app(data_dir)
            payload = {
                "website_id": "website_1",
                "agent_id": "db1",
                "agent_role": "db",
                "log_type": "syslog",
                "service": "system",
                "source_id": "src_syslog123456",
                "file_path": "/host/var/log/syslog",
                "timestamp": "2026-07-17T00:01:02+00:00",
                "message": "critical error disk full",
                "event_uid": "uid-raw-archive-duplicate",
            }

            app.handle_json("POST", "/api/ingest", {}, json.dumps(payload).encode("utf-8"))
            app.handle_json("POST", "/api/ingest", {}, json.dumps(payload).encode("utf-8"))

            files = list((data_dir / "raw_logs" / "website_1" / "db1").glob("*/*.jsonl"))
            self.assertEqual(len(files), 1)
            self.assertEqual(len(files[0].read_text(encoding="utf-8").splitlines()), 1)

    def test_legacy_and_source_aware_ingest_share_one_raw_archive_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            app = create_app(data_dir)
            common = {
                "website_id": "website_1",
                "agent_id": "db1",
                "agent_role": "db",
                "log_type": "syslog",
                "service": "system",
                "file_path": "/host/var/log/syslog",
                "timestamp": "2026-07-17T00:01:02+00:00",
                "message": "critical error disk full",
            }
            legacy = dict(common)
            source_aware = {
                **common,
                "source_id": "src_454567cf79f2a3f1e443",
                "source_confidence": 0.85,
                "event_uid": "evtuid_34affd9d282f1acc057b4b73",
            }

            app.handle_json("POST", "/api/ingest", {}, json.dumps(legacy).encode("utf-8"))
            app.handle_json("POST", "/api/ingest", {}, json.dumps(source_aware).encode("utf-8"))

            files = list((data_dir / "raw_logs" / "website_1" / "db1").glob("*/*.jsonl"))
            self.assertEqual(len(files), 1)
            self.assertIn("syslog--src_454567cf79", str(files[0]))
            rows = files[0].read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            stored = json.loads(rows[0])
            self.assertEqual(stored["source_id"], "src_454567cf79f2a3f1e443")

    def test_near_duplicate_same_source_message_does_not_create_second_raw_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            data_dir = Path(temp_dir)
            app = create_app(data_dir)
            common = {
                "website_id": "website_1",
                "agent_id": "db1",
                "agent_role": "db",
                "log_type": "syslog",
                "service": "system",
                "source_id": "src_454567cf79f2a3f1e443",
                "file_path": "/host/var/log/syslog",
                "message": "2026-07-17T15:19:03+07:00 host app: critical error disk full",
            }

            first_status, _first_headers, first_body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps({**common, "timestamp": "2026-07-17T08:19:04+00:00"}).encode("utf-8"),
            )
            second_status, _second_headers, second_body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps({**common, "timestamp": "2026-07-17T08:19:08+00:00"}).encode("utf-8"),
            )

            first = json.loads(first_body.decode("utf-8"))
            second = json.loads(second_body.decode("utf-8"))
            files = list((data_dir / "raw_logs" / "website_1" / "db1").glob("*/*.jsonl"))
            self.assertEqual(first_status, 201)
            self.assertEqual(second_status, 201)
            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(app.store.count_events("website_1"), 1)
            self.assertEqual(len(files), 1)
            self.assertEqual(len(files[0].read_text(encoding="utf-8").splitlines()), 1)

    def test_mock_ai_report_is_website_isolated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            events = [
                {
                    "website_id": "website_1",
                    "agent_id": "web01",
                    "agent_role": "web",
                    "timestamp": "2026-07-14T10:32:11+07:00",
                    "status_code": 502,
                    "message": "upstream timed out while reading response header from upstream",
                },
                {
                    "website_id": "website_1",
                    "agent_id": "db01",
                    "agent_role": "db",
                    "timestamp": "2026-07-14T10:32:20+07:00",
                    "message": "too many connections",
                },
                {
                    "website_id": "website_2",
                    "agent_id": "web02",
                    "agent_role": "web",
                    "timestamp": "2026-07-14T10:32:21+07:00",
                    "message": "permission denied",
                },
            ]
            for payload in events:
                app.handle_json("POST", "/api/ingest", {}, json.dumps(payload).encode("utf-8"))

            status, _headers, body = app.handle_json(
                "GET",
                "/api/analyze?website_id=website_1",
                {},
                b"",
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(response["website_id"], "website_1")
            self.assertEqual(set(response["agents_checked"]), {"web01", "db01"})
            self.assertNotIn("web02", response["summary"])

    def test_health_endpoint_is_json(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))

            status, headers, body = app.handle_json("GET", "/health", {}, b"")

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], "application/json")
            self.assertEqual(response["status"], "ok")


if __name__ == "__main__":
    unittest.main()
