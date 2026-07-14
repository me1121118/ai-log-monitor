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
