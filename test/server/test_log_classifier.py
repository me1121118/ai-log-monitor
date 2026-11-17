import unittest

from server.app.core import classify_event, normalize_event


class LogClassifierTests(unittest.TestCase):
    def test_nginx_access_success_is_traffic_normal(self):
        event = classify_event(self._event(
            service="nginx",
            log_type="nginx_access",
            file_path="/host/var/log/nginx/access.log",
            status_code=200,
            message="GET /health HTTP/1.1 200",
        ))

        self.assertEqual(event["signal_type"], "traffic")
        self.assertEqual(event["severity"], "normal")
        self.assertEqual(event["category"], "traffic_request")
        self.assertEqual(event["metadata"]["classification"]["rule_id"], "traffic.http_success.v1")

    def test_mariadb_connection_failure_is_database_problem(self):
        event = classify_event(self._event(
            service="mariadb",
            log_type="mysql_error",
            file_path="/host/var/log/mysql/error.log",
            message="Too many connections",
        ))

        self.assertEqual(event["signal_type"], "database")
        self.assertEqual(event["severity"], "problem")
        self.assertEqual(event["category"], "db_too_many_connections")
        self.assertEqual(
            event["metadata"]["classification"]["basis"],
            ["service_name", "source_path", "message_keyword"],
        )

    def test_kernel_oom_is_critical_system_signal(self):
        event = classify_event(self._event(
            service="kernel",
            log_type="syslog",
            file_path="/host/var/log/syslog",
            message="Out of memory: Kill process 1234",
        ))

        self.assertEqual(event["signal_type"], "system")
        self.assertEqual(event["severity"], "critical")
        self.assertEqual(event["category"], "out_of_memory")
        self.assertEqual(event["metadata"]["classification"]["rule_id"], "system.resource_critical.v1")

    def test_unknown_source_stays_conservative(self):
        event = classify_event(self._event(
            service="custom-agent",
            log_type="custom",
            file_path="/host/opt/custom/events.log",
            message="heartbeat received",
        ))

        self.assertEqual(event["signal_type"], "unknown")
        self.assertEqual(event["severity"], "normal")
        self.assertEqual(event["category"], "normal")
        self.assertEqual(event["metadata"]["classification"]["confidence"], 0.5)

    @staticmethod
    def _event(**overrides):
        payload = {
            "website_id": "website_1",
            "agent_id": "agent_1",
            "agent_role": "web",
            "timestamp": "2026-07-31T10:00:00+00:00",
            "message": "event",
        }
        payload.update(overrides)
        return normalize_event(payload, observed_at="2026-07-31T10:00:01+00:00")


if __name__ == "__main__":
    unittest.main()
