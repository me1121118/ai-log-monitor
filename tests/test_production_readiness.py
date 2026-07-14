import json
import tempfile
import unittest
from pathlib import Path

from server.app.app import create_app
from server.app.core import classify_event, normalize_event
from server.app.storage import Store


class ProductionReadinessTests(unittest.TestCase):
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

    def test_storage_retention_deletes_old_events_and_incidents(self):
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

            deleted = store.purge_older_than("2026-07-01T00:00:00+00:00")
            remaining = store.website_context("website_1", limit=10)

            self.assertEqual(deleted["events"], 1)
            self.assertEqual(deleted["incidents"], 1)
            self.assertEqual([event["category"] for event in remaining], ["db_too_many_connections"])


if __name__ == "__main__":
    unittest.main()
