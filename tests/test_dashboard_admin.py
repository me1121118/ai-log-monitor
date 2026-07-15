import json
import tempfile
import unittest
from pathlib import Path

from server.app.app import create_app


class DashboardAdminTests(unittest.TestCase):
    def test_create_and_list_websites(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            payload = {"website_id": "website_1", "name": "Website 1"}

            status, _headers, body = app.handle_json(
                "POST",
                "/api/websites",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            list_status, _list_headers, list_body = app.handle_json("GET", "/api/websites", {}, b"")

            created = json.loads(body.decode("utf-8"))
            listed = json.loads(list_body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(created["website_id"], "website_1")
            self.assertEqual(list_status, 200)
            self.assertEqual(listed["websites"][0]["name"], "Website 1")

    def test_list_agents_and_assign_agent_to_website(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), enroll_token="install-token")
            app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "install-token"},
                json.dumps({"agent_id": "web01", "agent_role": "web"}).encode("utf-8"),
            )
            payload = {"agent_id": "web01", "website_id": "website_1", "agent_role": "app"}

            status, _headers, body = app.handle_json(
                "POST",
                "/api/agents/assign",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            list_status, _list_headers, list_body = app.handle_json("GET", "/api/agents", {}, b"")

            assigned = json.loads(body.decode("utf-8"))
            listed = json.loads(list_body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(assigned["website_id"], "website_1")
            self.assertEqual(assigned["agent_role"], "app")
            self.assertEqual(list_status, 200)
            self.assertEqual(listed["agents"][0]["website_id"], "website_1")

    def test_close_incident(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            _, _, ingest_body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:11+07:00",
                        "message": "upstream timed out while reading response header from upstream",
                    }
                ).encode("utf-8"),
            )
            incident_id = json.loads(ingest_body.decode("utf-8"))["incident_id"]

            status, _headers, body = app.handle_json(
                "POST",
                f"/api/incidents/{incident_id}/close",
                {},
                b"{}",
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(response["incident_id"], incident_id)
            self.assertEqual(response["status"], "closed")

    def test_import_log_file_creates_website_scoped_incident(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            payload = {
                "website_id": "website_1",
                "filename": "nginx-error.log",
                "content": "GET /health 200\nupstream timed out while reading response header from upstream\n",
                "agent_id": "manual_upload",
                "agent_role": "manual",
                "log_type": "uploaded_file",
                "service": "nginx",
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/files/import",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            response = json.loads(body.decode("utf-8"))

            self.assertEqual(status, 201)
            self.assertEqual(response["website_id"], "website_1")
            self.assertEqual(response["imported_lines"], 2)
            self.assertEqual(response["problem_lines"], 1)
            self.assertTrue(response["incident_ids"])

            analyze_status, _analyze_headers, analyze_body = app.handle_json(
                "GET",
                "/api/analyze?website_id=website_1",
                {},
                b"",
            )
            report = json.loads(analyze_body.decode("utf-8"))
            self.assertEqual(analyze_status, 200)
            self.assertEqual(report["agents_checked"], ["manual_upload"])
            self.assertIn("upstream_timeout", report["summary"])

    def test_empty_dashboard_waits_for_first_connection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))

            html = app.dashboard_html().decode("utf-8")

            self.assertIn('class="empty-dashboard"', html)
            self.assertIn("Waiting for agent connection", html)
            self.assertNotIn('class="website-board"', html)
            self.assertNotIn('data-role="website-tile"', html)
            self.assertNotIn("Import Log File", html)
            self.assertNotIn("Advanced Setup", html)
            self.assertNotIn("Data Tables", html)

    def test_dashboard_html_shows_connected_websites_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "change-this-install-token"},
                json.dumps({"agent_id": "web01", "agent_role": "web", "website_id": "website_1"}).encode("utf-8"),
            )

            html = app.dashboard_html().decode("utf-8")

            self.assertIn('class="website-board"', html)
            self.assertIn('data-role="website-tile"', html)
            self.assertIn("website_1", html)
            self.assertNotIn("website_2", html)
            self.assertNotIn("website_5", html)

    def test_dashboard_html_filters_tables_by_selected_website(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            for payload in [
                {
                    "website_id": "website_1",
                    "agent_id": "web01",
                    "agent_role": "web",
                    "timestamp": "2026-07-14T10:32:11+07:00",
                    "message": "upstream timed out while reading response header from upstream",
                },
                {
                    "website_id": "website_2",
                    "agent_id": "web02",
                    "agent_role": "web",
                    "timestamp": "2026-07-14T10:32:12+07:00",
                    "message": "permission denied",
                },
            ]:
                app.handle_json("POST", "/api/ingest", {}, json.dumps(payload).encode("utf-8"))
                app.handle_json(
                    "POST",
                    "/api/agents/register",
                    {"X-Enroll-Token": "change-this-install-token"},
                    json.dumps(
                        {
                            "agent_id": payload["agent_id"],
                            "agent_role": payload["agent_role"],
                            "website_id": payload["website_id"],
                        }
                    ).encode("utf-8"),
                )

            html = app.dashboard_html(selected_website_id="website_1").decode("utf-8")

            self.assertIn("Selected Website: website_1", html)
            self.assertIn("web01", html)
            self.assertIn("upstream_timeout", html)
            self.assertNotIn("web02", html)
            self.assertNotIn("permission_denied", html)
            self.assertIn('href="/?website_id=website_1"', html)
            self.assertIn('href="/?website_id=website_2"', html)

    def test_selected_website_dashboard_shows_machine_monitor(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            for agent in [
                {"agent_id": "web01", "agent_role": "web", "website_id": "website_1"},
                {"agent_id": "db01", "agent_role": "db", "website_id": "website_1"},
                {"agent_id": "web02", "agent_role": "web", "website_id": "website_2"},
            ]:
                app.handle_json(
                    "POST",
                    "/api/agents/register",
                    {"X-Enroll-Token": "change-this-install-token"},
                    json.dumps(agent).encode("utf-8"),
                )
            for payload in [
                {
                    "website_id": "website_1",
                    "agent_id": "web01",
                    "agent_role": "web",
                    "timestamp": "2026-07-14T10:32:11+07:00",
                    "message": "GET /health 200",
                },
                {
                    "website_id": "website_1",
                    "agent_id": "db01",
                    "agent_role": "db",
                    "timestamp": "2026-07-14T10:32:12+07:00",
                    "message": "too many connections",
                },
                {
                    "website_id": "website_2",
                    "agent_id": "web02",
                    "agent_role": "web",
                    "timestamp": "2026-07-14T10:32:13+07:00",
                    "message": "permission denied",
                },
            ]:
                app.handle_json("POST", "/api/ingest", {}, json.dumps(payload).encode("utf-8"))

            html = app.dashboard_html(selected_website_id="website_1").decode("utf-8")

            self.assertIn("Machine Monitor", html)
            self.assertIn('class="website-detail"', html)
            self.assertIn('class="machine-rail"', html)
            self.assertIn('class="website-summary"', html)
            self.assertIn('class="log-panel"', html)
            self.assertIn('data-machine="web01"', html)
            self.assertIn('data-machine="db01"', html)
            self.assertIn("web01", html)
            self.assertIn("db01", html)
            self.assertIn("db_too_many_connections", html)
            self.assertIn("Problem", html)
            self.assertNotIn('data-machine="web02"', html)
            self.assertNotIn("web02", html)
            self.assertNotIn("permission_denied", html)

    def test_selected_website_dashboard_has_fleet_layout_and_ai_side_panel(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            for agent in [
                {"agent_id": "web01", "agent_role": "web", "website_id": "website_1"},
                {"agent_id": "db01", "agent_role": "db", "website_id": "website_1"},
            ]:
                app.handle_json(
                    "POST",
                    "/api/agents/register",
                    {"X-Enroll-Token": "change-this-install-token"},
                    json.dumps(agent).encode("utf-8"),
                )
            app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(
                    {
                        "website_id": "website_1",
                        "agent_id": "db01",
                        "agent_role": "db",
                        "timestamp": "2026-07-14T10:32:12+07:00",
                        "message": "too many connections",
                    }
                ).encode("utf-8"),
            )

            html = app.dashboard_html(selected_website_id="website_1").decode("utf-8")

            self.assertIn('class="ops-shell"', html)
            self.assertIn('class="sidebar"', html)
            self.assertIn('class="fleet-grid"', html)
            self.assertIn('class="ai-side-panel"', html)
            self.assertIn("AI Summary Panel", html)
            self.assertIn("Suspected Machine", html)
            self.assertIn("Log Evidence", html)
            self.assertIn("db01", html)
            self.assertIn("too many connections", html)
            self.assertNotIn("CPU", html)
            self.assertNotIn("RAM", html)
            self.assertNotIn("Net", html)

    def test_unknown_website_selection_returns_empty_dashboard(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))

            html = app.dashboard_html(selected_website_id="website_5").decode("utf-8")

            self.assertIn('class="empty-dashboard"', html)
            self.assertNotIn("Selected Website: website_5", html)
            self.assertNotIn('class="website-detail"', html)


if __name__ == "__main__":
    unittest.main()
