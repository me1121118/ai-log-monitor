import json
import tempfile
import unittest
from pathlib import Path

from server.app.app import create_app


class NotificationTests(unittest.TestCase):
    def test_critical_ingest_auto_analyzes_and_sends_configured_webhooks(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai.yaml"
            config_path.write_text(
                """
ai:
  enabled: true
  mode: "mock"
analysis:
  auto_analyze: true
  auto_analyze_min_severity: "critical"
  time_window_minutes: 30
notifications:
  enabled: true
  line_webhook_url: "http://notify.local/line"
  google_chat_webhook_url: "http://notify.local/google-chat"
""".strip(),
                encoding="utf-8",
            )
            sent = []

            def capture_post(url, headers, payload, timeout):
                sent.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
                return {"ok": True}

            app = create_app(Path(temp_dir), ai_config_path=config_path, notification_post=capture_post)
            app.handle_json(
                "POST",
                "/api/agents/register",
                {"X-Enroll-Token": "change-this-install-token"},
                json.dumps(
                    {
                        "agent_id": "web01",
                        "agent_role": "web",
                        "website_id": "website_1",
                    }
                ).encode("utf-8"),
            )

            status, _headers, body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-17T00:00:00+00:00",
                        "message": "disk full on /var",
                    }
                ).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(response["severity"], "critical")
            self.assertEqual(response["auto_analysis"]["notifications"]["sent"], 2)
            self.assertEqual({item["url"] for item in sent}, {"http://notify.local/line", "http://notify.local/google-chat"})
            alert_text = "\n".join(item["payload"]["text"] for item in sent)
            self.assertIn("website_1", alert_text)
            self.assertIn("web01", alert_text)
            self.assertIn("disk_full", alert_text)
            self.assertIn("สาเหตุที่สงสัย", alert_text)

    def test_problem_ingest_does_not_auto_notify_by_default(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            sent = []

            def capture_post(url, headers, payload, timeout):
                sent.append(payload)
                return {"ok": True}

            app = create_app(Path(temp_dir), notification_post=capture_post)
            status, _headers, body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-17T00:00:00+00:00",
                        "message": "upstream timed out",
                    }
                ).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(response["severity"], "problem")
            self.assertNotIn("auto_analysis", response)
            self.assertEqual(sent, [])

    def test_alert_notifications_redact_sensitive_log_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai.yaml"
            config_path.write_text(
                """
ai:
  enabled: true
  mode: "mock"
analysis:
  auto_analyze: true
  auto_analyze_min_severity: "critical"
notifications:
  enabled: true
  line_webhook_url: "http://notify.local/line"
privacy:
  redact_before_send: true
  redact_fields:
    - "password"
    - "token"
    - "authorization"
""".strip(),
                encoding="utf-8",
            )
            sent = []

            def capture_post(url, headers, payload, timeout):
                sent.append(payload)
                return {"ok": True}

            app = create_app(Path(temp_dir), ai_config_path=config_path, notification_post=capture_post)
            status, _headers, body = app.handle_json(
                "POST",
                "/api/ingest",
                {},
                json.dumps(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-17T00:00:00+00:00",
                        "message": "disk full password=supersecret token=abc123 Authorization: Bearer live-token-123",
                    }
                ).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 201)
            self.assertEqual(response["severity"], "critical")
            alert_text = sent[0]["text"]
            self.assertNotIn("supersecret", alert_text)
            self.assertNotIn("abc123", alert_text)
            self.assertNotIn("live-token-123", alert_text)
            self.assertIn("[REDACTED]", alert_text)


if __name__ == "__main__":
    unittest.main()
