import unittest

from server.app.core import classify_event, normalize_event


class EventCoreTests(unittest.TestCase):
    def test_normalize_event_requires_routing_identity(self):
        payload = {
            "agent_id": "web01",
            "agent_role": "web",
            "message": "nginx started",
            "timestamp": "2026-07-14T10:00:00+07:00",
        }

        with self.assertRaises(ValueError) as raised:
            normalize_event(payload, observed_at="2026-07-14T10:00:01+07:00")

        self.assertIn("website_id", str(raised.exception))

    def test_classifies_http_200_as_normal(self):
        event = normalize_event(
            {
                "website_id": "website_1",
                "agent_id": "web01",
                "agent_role": "web",
                "log_type": "nginx_access",
                "service": "nginx",
                "timestamp": "2026-07-14T10:00:00+07:00",
                "status_code": 200,
                "message": "GET /health 200",
            },
            observed_at="2026-07-14T10:00:01+07:00",
        )

        classified = classify_event(event)

        self.assertEqual(classified["severity"], "normal")
        self.assertEqual(classified["category"], "normal")
        self.assertTrue(classified["fingerprint"].startswith("fp_"))

    def test_classifies_nginx_502_timeout_as_problem(self):
        event = normalize_event(
            {
                "website_id": "website_1",
                "agent_id": "web01",
                "agent_role": "web",
                "log_type": "nginx_error",
                "service": "nginx",
                "timestamp": "2026-07-14T10:32:11+07:00",
                "status_code": 502,
                "message": "upstream timed out while reading response header from upstream",
            },
            observed_at="2026-07-14T10:32:12+07:00",
        )

        classified = classify_event(event)

        self.assertEqual(classified["severity"], "problem")
        self.assertEqual(classified["category"], "upstream_timeout")
        self.assertEqual(classified["fingerprint"], "fp_nginx_upstream_timeout")

    def test_classifies_disk_full_as_critical(self):
        event = normalize_event(
            {
                "website_id": "website_1",
                "agent_id": "db01",
                "agent_role": "db",
                "log_type": "system",
                "service": "kernel",
                "timestamp": "2026-07-14T10:33:00+07:00",
                "message": "No space left on device: disk full",
            },
            observed_at="2026-07-14T10:33:01+07:00",
        )

        classified = classify_event(event)

        self.assertEqual(classified["severity"], "critical")
        self.assertEqual(classified["category"], "disk_full")


if __name__ == "__main__":
    unittest.main()
