import tempfile
import unittest
from pathlib import Path

from server.app.core import classify_event, normalize_event
from server.app.storage import Store


class EventEnvelopeTests(unittest.TestCase):
    def test_normalize_event_preserves_source_and_timestamp_confidence(self):
        event = normalize_event(
            {
                "website_id": "website_1",
                "agent_id": "app01",
                "agent_role": "app",
                "timestamp": "not-a-real-time",
                "message": "Traceback line 1\n  line 2",
                "source_id": "src_app01_app",
                "source_confidence": 0.82,
                "event_uid": "uid-1",
                "multiline": True,
                "line_count": 2,
            },
            observed_at="2026-07-17T00:00:00+00:00",
        )

        self.assertEqual(event["source_id"], "src_app01_app")
        self.assertEqual(event["source_confidence"], 0.82)
        self.assertEqual(event["event_uid"], "uid-1")
        self.assertTrue(event["multiline"])
        self.assertEqual(event["line_count"], 2)
        self.assertEqual(event["timestamp"], "2026-07-17T00:00:00+00:00")
        self.assertEqual(event["timestamp_confidence"], "fallback_observed_at")

    def test_duplicate_event_uid_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()
            payload = {
                "website_id": "website_1",
                "agent_id": "app01",
                "agent_role": "app",
                "timestamp": "2026-07-17T00:00:00+00:00",
                "message": "connection refused",
                "event_uid": "uid-duplicate",
                "source_id": "src_app01_app",
            }
            event = classify_event(normalize_event(payload))

            first = store.ingest_event(event)
            second = store.ingest_event(event)

            self.assertEqual(first["event_id"], second["event_id"])
            self.assertTrue(first["stored"])
            self.assertFalse(second["stored"])
            self.assertEqual(store.count_events("website_1"), 1)

    def test_legacy_event_without_source_id_dedupes_with_source_aware_event_for_same_file(self):
        common = {
            "website_id": "website_1",
            "agent_id": "db1",
            "agent_role": "db",
            "log_type": "syslog",
            "service": "system",
            "file_path": "/host/var/log/syslog",
            "timestamp": "2026-07-17T00:00:00+00:00",
            "message": "critical error disk full",
        }

        legacy = normalize_event(common)
        source_aware = normalize_event(
            {
                **common,
                "source_id": "src_454567cf79f2a3f1e443",
                "source_confidence": 0.85,
                "event_uid": "evtuid_34affd9d282f1acc057b4b73",
            }
        )

        self.assertEqual(legacy["source_id"], "src_454567cf79f2a3f1e443")
        self.assertEqual(legacy["event_id"], source_aware["event_id"])

    def test_stored_event_exposes_source_metadata_as_top_level_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()
            event = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "app01",
                        "agent_role": "app",
                        "timestamp": "2026-07-17T00:00:00+00:00",
                        "message": "critical error disk full",
                        "source_id": "src_app01_nginx",
                        "source_confidence": 0.91,
                        "event_uid": "uid-source-meta",
                        "multiline": False,
                        "line_count": 1,
                    }
                )
            )

            store.ingest_event(event)
            stored = store.recent_events()[0]

            self.assertEqual(stored["source_id"], "src_app01_nginx")
            self.assertEqual(stored["source_confidence"], 0.91)
            self.assertEqual(stored["event_uid"], "uid-source-meta")
            self.assertFalse(stored["multiline"])
            self.assertEqual(stored["line_count"], 1)
            self.assertEqual(stored["metadata"]["source_id"], "src_app01_nginx")


if __name__ == "__main__":
    unittest.main()
