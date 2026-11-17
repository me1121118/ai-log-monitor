import tempfile
import unittest
from pathlib import Path

from server.app.core import classify_event, normalize_event
from server.app.storage import Store


class ReliabilityTests(unittest.TestCase):
    def test_duplicate_problem_event_does_not_increment_incident_count(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()
            event = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "app01",
                        "agent_role": "app",
                        "timestamp": "2026-07-17T01:00:00+00:00",
                        "message": "connection refused to db01:3306",
                        "event_uid": "uid-retry-same-event",
                    }
                )
            )

            first = store.ingest_event(event)
            second = store.ingest_event(event)
            incidents = store.list_incidents("website_1")

            self.assertEqual(first["incident_id"], second["incident_id"])
            self.assertEqual(store.count_events("website_1"), 1)
            self.assertEqual(len(incidents), 1)
            self.assertEqual(incidents[0]["event_count"], 1)

    def test_agent_spool_loss_marker_is_visible_problem(self):
        event = classify_event(
            normalize_event(
                {
                    "website_id": "website_1",
                    "agent_id": "app01",
                    "agent_role": "app",
                    "timestamp": "2026-07-17T01:00:00+00:00",
                    "message": "agent_spool_loss_marker dropped=42 reason=spool_max_bytes",
                    "event_uid": "uid-loss-marker",
                }
            )
        )

        self.assertEqual(event["severity"], "problem")
        self.assertEqual(event["category"], "agent_data_loss")


if __name__ == "__main__":
    unittest.main()
