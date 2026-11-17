import unittest

from server.app.rolling_buffer import RollingLogBuffer


class RollingLogBufferTests(unittest.TestCase):
    def test_context_is_isolated_and_limited_per_source(self):
        now = [0.0]
        buffer = RollingLogBuffer(max_age_seconds=300, max_entries_per_source=2, clock=lambda: now[0])

        for index in range(3):
            buffer.append(self._event("website_1", "web1", "src_access", f"line {index}"))
        buffer.append(self._event("website_1", "web2", "src_access", "other agent"))
        buffer.append(self._event("website_2", "web1", "src_access", "other website"))

        context = buffer.context("website_1", "web1", "src_access")

        self.assertEqual([item["message"] for item in context], ["line 1", "line 2"])

    def test_context_expires_by_arrival_time(self):
        now = [0.0]
        buffer = RollingLogBuffer(max_age_seconds=300, max_entries_per_source=200, clock=lambda: now[0])
        buffer.append(self._event("website_1", "db1", "src_error", "ready"))

        now[0] = 301.0

        self.assertEqual(buffer.context("website_1", "db1", "src_error"), [])

    def test_global_source_limit_evicts_least_recent_source(self):
        buffer = RollingLogBuffer(max_sources=2, max_total_entries=10)
        buffer.append(self._event("website_1", "web1", "src_1", "one"))
        buffer.append(self._event("website_1", "web1", "src_2", "two"))
        buffer.append(self._event("website_1", "web1", "src_3", "three"))

        self.assertEqual(buffer.context("website_1", "web1", "src_1"), [])
        self.assertEqual(buffer.context("website_1", "web1", "src_3")[0]["message"], "three")

    @staticmethod
    def _event(website_id: str, agent_id: str, source_id: str, message: str) -> dict:
        return {
            "website_id": website_id,
            "agent_id": agent_id,
            "source_id": source_id,
            "timestamp": "2026-07-30T00:00:00+00:00",
            "observed_at": "2026-07-30T00:00:00+00:00",
            "severity": "normal",
            "category": "normal",
            "service": "nginx",
            "log_type": "access",
            "file_path": "/host/var/log/nginx/access.log",
            "message": message,
        }


if __name__ == "__main__":
    unittest.main()
