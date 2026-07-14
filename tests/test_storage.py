import tempfile
import unittest
from pathlib import Path

from server.app.core import classify_event, normalize_event
from server.app.storage import Store


class StorageFlowTests(unittest.TestCase):
    def test_problem_event_creates_incident_but_normal_event_does_not(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()

            normal = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:00:00+07:00",
                        "status_code": 200,
                        "message": "GET /health 200",
                    },
                    observed_at="2026-07-14T10:00:01+07:00",
                )
            )
            problem = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:11+07:00",
                        "status_code": 502,
                        "message": "upstream timed out while reading response header from upstream",
                    },
                    observed_at="2026-07-14T10:32:12+07:00",
                )
            )

            normal_result = store.ingest_event(normal)
            problem_result = store.ingest_event(problem)

            self.assertIsNone(normal_result["incident_id"])
            self.assertIsNotNone(problem_result["incident_id"])
            self.assertEqual(len(store.list_incidents("website_1")), 1)

    def test_website_context_never_crosses_boundaries(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()

            event_1 = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:11+07:00",
                        "status_code": 502,
                        "message": "upstream timed out while reading response header from upstream",
                    },
                    observed_at="2026-07-14T10:32:12+07:00",
                )
            )
            event_2 = classify_event(
                normalize_event(
                    {
                        "website_id": "website_2",
                        "agent_id": "web02",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:12+07:00",
                        "status_code": 502,
                        "message": "upstream timed out while reading response header from upstream",
                    },
                    observed_at="2026-07-14T10:32:13+07:00",
                )
            )

            store.ingest_event(event_1)
            store.ingest_event(event_2)
            context = store.website_context("website_1", limit=10)

            self.assertEqual({row["website_id"] for row in context}, {"website_1"})
            self.assertEqual({row["agent_id"] for row in context}, {"web01"})


if __name__ == "__main__":
    unittest.main()
