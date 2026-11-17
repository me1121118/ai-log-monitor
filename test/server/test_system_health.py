import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from server.app.app import create_app


class SystemHealthTests(unittest.TestCase):
    def test_system_health_reports_stale_agents_and_core_checks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            self._register_agent(app, "web01", "website_1")
            self._register_agent(app, "db01", "website_1")
            self._heartbeat(app, "web01", "website_1", "2000-01-01T00:00:00+00:00")
            self._heartbeat(app, "db01", "website_1", datetime.now(timezone.utc).isoformat())

            status, _headers, body = app.handle_json("GET", "/api/system/health", {}, b"")

            payload = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(payload["status"], "degraded")
            self.assertEqual(payload["checks"]["database"]["status"], "ok")
            self.assertEqual(payload["checks"]["data_dir"]["status"], "ok")
            self.assertEqual(payload["checks"]["agents"]["total"], 2)
            self.assertEqual(payload["checks"]["agents"]["stale"], 1)
            self.assertEqual(payload["checks"]["agents"]["offline_agent_ids"], ["web01"])
            self.assertEqual(payload["checks"]["incidents"]["open"], 0)

    def test_system_health_is_admin_protected_when_admin_login_is_enabled(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), admin_token="secret-admin")

            missing_status, _missing_headers, missing_body = app.handle_json(
                "GET",
                "/api/system/health",
                {},
                b"",
            )
            ok_status, _ok_headers, ok_body = app.handle_json(
                "GET",
                "/api/system/health",
                {"X-Admin-Token": "secret-admin"},
                b"",
            )

            self.assertEqual(missing_status, 401)
            self.assertEqual(json.loads(missing_body.decode("utf-8"))["error"], "admin authentication required")
            self.assertEqual(ok_status, 200)
            self.assertEqual(json.loads(ok_body.decode("utf-8"))["status"], "ok")

    def test_settings_page_surfaces_live_system_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            self._register_agent(app, "web01", "website_1")
            self._heartbeat(app, "web01", "website_1", "2000-01-01T00:00:00+00:00")

            html = app.dashboard_html(page="settings").decode("utf-8")

            self.assertIn("System Health", html)
            self.assertIn("Degraded", html)
            self.assertIn("1 stale agent", html)
            self.assertIn("web01", html)

    def test_agent_list_api_includes_server_side_health_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            self._register_agent(app, "web01", "website_1")
            self._register_agent(app, "db01", "website_1")
            self._heartbeat(app, "web01", "website_1", "2000-01-01T00:00:00+00:00")
            self._heartbeat(app, "db01", "website_1", datetime.now(timezone.utc).isoformat())

            status, _headers, body = app.handle_json("GET", "/api/agents", {}, b"")

            payload = json.loads(body.decode("utf-8"))
            agents = {agent["agent_id"]: agent for agent in payload["agents"]}
            self.assertEqual(status, 200)
            self.assertEqual(agents["web01"]["status"], "active")
            self.assertEqual(agents["web01"]["health_status"], "stale")
            self.assertGreater(agents["web01"]["seconds_since_seen"], 90)
            self.assertEqual(agents["db01"]["health_status"], "active")
            self.assertLessEqual(agents["db01"]["seconds_since_seen"], 90)

    def test_agents_page_shows_server_side_stale_status(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            self._register_agent(app, "web01", "website_1")
            self._heartbeat(app, "web01", "website_1", "2000-01-01T00:00:00+00:00")

            html = app.dashboard_html(selected_website_id="website_1", page="agents").decode("utf-8")

            self.assertIn("web01", html)
            self.assertIn("stale", html)
            self.assertIn("status-badge status-warning", html)

    def _register_agent(self, app, agent_id: str, website_id: str) -> None:
        app.handle_json(
            "POST",
            "/api/agents/register",
            {"X-Enroll-Token": "change-this-install-token"},
            json.dumps(
                {
                    "agent_id": agent_id,
                    "agent_role": "web",
                    "website_id": website_id,
                    "hostname": f"{agent_id}.local",
                    "source_ip": "10.1.0.21",
                }
            ).encode("utf-8"),
        )

    def _heartbeat(self, app, agent_id: str, website_id: str, observed_at: str) -> None:
        app.handle_json(
            "POST",
            "/api/agents/heartbeat",
            {},
            json.dumps(
                {
                    "agent_id": agent_id,
                    "website_id": website_id,
                    "status": "active",
                    "observed_at": observed_at,
                }
            ).encode("utf-8"),
        )


if __name__ == "__main__":
    unittest.main()
