import json
import tempfile
import threading
import unittest
from pathlib import Path

from server.app.app import create_app
from server.app.core import classify_event, normalize_event
from server.app.storage import Store
import server.main as server_main


class ProductionReadinessTests(unittest.TestCase):
    def test_serve_until_stopped_closes_server_without_serving(self):
        class FakeServer:
            timeout = None
            handled = 0
            closed = False

            def handle_request(self):
                self.handled += 1

            def server_close(self):
                self.closed = True

        stop_event = threading.Event()
        stop_event.set()
        server = FakeServer()
        server_main.serve_until_stopped(server, stop_event)
        self.assertEqual(server.timeout, 0.5)
        self.assertEqual(server.handled, 0)
        self.assertTrue(server.closed)

    def test_static_file_resolution_keeps_nested_path_segments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            static_dir = Path(temp_dir)
            target = static_dir / "css" / "styles.css"
            target.parent.mkdir(parents=True)
            target.write_text("body {}", encoding="utf-8")

            resolver = getattr(server_main, "resolve_static_file_path", None)

            self.assertIsNotNone(resolver)
            self.assertEqual(resolver(static_dir, "/static/css/styles.css"), target.resolve())

    def test_server_config_loader_reads_public_runtime_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "config.yaml"
            config_path.write_text(
                """
server:
  public_url: "http://logs.lan:9999"
  bind: "127.0.0.1"
  port: 9999
""".strip(),
                encoding="utf-8",
            )

            values = server_main.load_server_config(config_path)

            self.assertEqual(values["public_url"], "http://logs.lan:9999")
            self.assertEqual(values["bind"], "127.0.0.1")
            self.assertEqual(values["port"], "9999")

    def test_agent_register_accepts_case_insensitive_enroll_header(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), enroll_token="install-token")

            status, _headers, body = app.handle_json(
                "POST",
                "/api/agents/register",
                {"x-enroll-token": "install-token"},
                json.dumps(
                    {
                        "agent_id": "web01",
                        "agent_role": "web",
                        "website_id": "website_1",
                    }
                ).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(response["agent_id"], "web01")

    def test_admin_token_protects_management_api_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), admin_token="admin-token")

            health_status, _health_headers, _health_body = app.handle_json("GET", "/health", {}, b"")
            blocked_status, _blocked_headers, blocked_body = app.handle_json("GET", "/api/websites", {}, b"")
            allowed_status, _allowed_headers, allowed_body = app.handle_json(
                "GET",
                "/api/websites",
                {"X-Admin-Token": "admin-token"},
                b"",
            )

            blocked = json.loads(blocked_body.decode("utf-8"))
            allowed = json.loads(allowed_body.decode("utf-8"))
            self.assertEqual(health_status, 200)
            self.assertEqual(blocked_status, 401)
            self.assertEqual(blocked["error"], "admin authentication required")
            self.assertEqual(allowed_status, 200)
            self.assertEqual(allowed["websites"], [])

    def test_normal_login_uses_username_password_and_session_cookie(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(
                Path(temp_dir),
                admin_token="session-secret",
                admin_user="admin",
                admin_password="strong-password",
            )

            login_html = app.login_html().decode("utf-8")
            wrong_status, _wrong_headers, wrong_body = app.login_response(
                b"admin_user=admin&admin_password=wrong&next=/"
            )
            ok_status, ok_headers, _ok_body = app.login_response(
                b"admin_user=admin&admin_password=strong-password&next=/api/websites"
            )
            session_cookie = ok_headers["Set-Cookie"].split(";", 1)[0]
            allowed_status, _allowed_headers, allowed_body = app.handle_json(
                "GET",
                "/api/websites",
                {"Cookie": session_cookie},
                b"",
            )

            wrong_page = wrong_body.decode("utf-8")
            allowed = json.loads(allowed_body.decode("utf-8"))
            self.assertIn('name="admin_user"', login_html)
            self.assertIn('name="admin_password"', login_html)
            self.assertNotIn('name="admin_token"', login_html)
            self.assertEqual(wrong_status, 401)
            self.assertIn("Invalid username or password", wrong_page)
            self.assertEqual(ok_status, 302)
            self.assertIn("admin_session=", ok_headers["Set-Cookie"])
            self.assertEqual(ok_headers["Location"], "/api/websites")
            self.assertEqual(allowed_status, 200)
            self.assertEqual(allowed["websites"], [])

    def test_agent_token_protects_ingest_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), enroll_token="install-token", enforce_agent_token=True)
            _status, _headers, register_body = app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "install-token"},
                json.dumps(
                    {
                        "agent_id": "web01",
                        "agent_role": "web",
                        "website_id": "website_1",
                    }
                ).encode("utf-8"),
            )
            agent_token = json.loads(register_body.decode("utf-8"))["agent_token"]
            payload = {
                "website_id": "website_1",
                "agent_id": "web01",
                "agent_role": "web",
                "timestamp": "2026-07-14T10:32:11+07:00",
                "message": "upstream timed out while reading response header from upstream",
            }

            missing_status, _missing_headers, missing_body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            wrong_status, _wrong_headers, _wrong_body = app.handle_json(
                "POST",
                "/api/ingest",
                {"X-Agent-Token": "wrong-token"},
                json.dumps(payload).encode("utf-8"),
            )
            ok_status, _ok_headers, ok_body = app.handle_json(
                "POST",
                "/api/ingest",
                {"X-Agent-Token": agent_token},
                json.dumps(payload).encode("utf-8"),
            )

            missing = json.loads(missing_body.decode("utf-8"))
            ok = json.loads(ok_body.decode("utf-8"))
            self.assertEqual(missing_status, 401)
            self.assertEqual(missing["error"], "invalid agent token")
            self.assertEqual(wrong_status, 401)
            self.assertEqual(ok_status, 201)
            self.assertEqual(ok["severity"], "problem")

    def test_agent_token_protects_log_source_reporting_when_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(
                Path(temp_dir),
                enroll_token="install-token",
                admin_token="admin-token",
                enforce_agent_token=True,
            )
            _status, _headers, register_body = app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "install-token"},
                json.dumps(
                    {
                        "agent_id": "web01",
                        "agent_role": "web",
                        "website_id": "website_1",
                    }
                ).encode("utf-8"),
            )
            agent_token = json.loads(register_body.decode("utf-8"))["agent_token"]
            payload = {
                "website_id": "website_1",
                "agent_id": "web01",
                "sources": [
                    {
                        "source_id": "src_web01_app",
                        "name": "app",
                        "path": "/opt/shop/logs/app.log",
                        "source_type": "custom_app",
                        "service": "shop",
                        "classification": "custom_app",
                        "confidence": 0.82,
                        "status": "readable",
                        "last_seen_at": "2026-07-17T00:00:00+00:00",
                    }
                ],
            }

            missing_status, _missing_headers, missing_body = app.handle_json(
                "POST",
                "/api/log-sources",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            ok_status, _ok_headers, ok_body = app.handle_json(
                "POST",
                "/api/log-sources",
                {"X-Agent-Token": agent_token},
                json.dumps(payload).encode("utf-8"),
            )

            missing = json.loads(missing_body.decode("utf-8"))
            ok = json.loads(ok_body.decode("utf-8"))
            self.assertEqual(missing_status, 401)
            self.assertEqual(missing["error"], "invalid agent token")
            self.assertEqual(ok_status, 201)
            self.assertEqual(ok["stored"], 1)

    def test_agent_token_protects_heartbeat_and_updates_last_seen(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(
                Path(temp_dir),
                enroll_token="install-token",
                enforce_agent_token=True,
            )
            _register_status, _register_headers, register_body = app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "install-token"},
                json.dumps(
                    {
                        "agent_id": "web01",
                        "agent_role": "web",
                        "website_id": "website_1",
                    }
                ).encode("utf-8"),
            )
            agent_token = json.loads(register_body.decode("utf-8"))["agent_token"]

            bad_status, _bad_headers, bad_body = app.handle_json(
                "POST",
                "/api/agents/heartbeat",
                {"X-Agent-Token": "wrong-token"},
                json.dumps(
                    {
                        "agent_id": "web01",
                        "status": "active",
                        "observed_at": "2026-07-17T00:01:00+00:00",
                    }
                ).encode("utf-8"),
            )
            ok_status, _ok_headers, ok_body = app.handle_json(
                "POST",
                "/api/agents/heartbeat",
                {"X-Agent-Token": agent_token},
                json.dumps(
                    {
                        "agent_id": "web01",
                        "status": "active",
                        "observed_at": "2026-07-17T00:02:00+00:00",
                        "metrics": {"log_sources": 3},
                    }
                ).encode("utf-8"),
            )

            bad = json.loads(bad_body.decode("utf-8"))
            ok = json.loads(ok_body.decode("utf-8"))
            agents = app.store.list_agents()

            self.assertEqual(bad_status, 401)
            self.assertEqual(bad["error"], "invalid agent token")
            self.assertEqual(ok_status, 200)
            self.assertEqual(ok["agent_id"], "web01")
            self.assertEqual(agents[0]["last_seen_at"], "2026-07-17T00:02:00+00:00")
            self.assertEqual(agents[0]["status"], "active")

    def test_storage_retention_deletes_old_events_but_keeps_incidents_and_memory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "database.db")
            store.init()
            old_event = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-06-01T10:00:00+00:00",
                        "message": "upstream timed out",
                    },
                    observed_at="2026-06-01T10:00:00+00:00",
                )
            )
            new_event = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:00:00+00:00",
                        "message": "too many connections",
                    },
                    observed_at="2026-07-14T10:00:00+00:00",
                )
            )
            store.ingest_event(old_event)
            store.ingest_event(new_event)
            store.upsert_incident_memory(
                {
                    "website_id": "website_1",
                    "fingerprint": old_event["fingerprint"],
                    "category": old_event["category"],
                    "root_cause": "old upstream timeout pattern",
                    "suggested_action": "check upstream saturation first",
                    "observed_at": "2026-06-01T10:00:00+00:00",
                    "confidence": 0.8,
                }
            )

            deleted = store.purge_older_than("2026-07-01T00:00:00+00:00")
            remaining = store.website_context("website_1", limit=10)
            incidents = store.list_incidents("website_1")
            memory = store.match_incident_memory("website_1", [old_event["fingerprint"]])

            self.assertEqual(deleted["events"], 1)
            self.assertEqual(deleted["incidents"], 0)
            self.assertEqual(deleted["memory"], 0)
            self.assertEqual([event["category"] for event in remaining], ["db_too_many_connections"])
            self.assertEqual(len(incidents), 2)
            self.assertEqual(memory[0]["root_cause"], "old upstream timeout pattern")


if __name__ == "__main__":
    unittest.main()
