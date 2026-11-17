import json
import tempfile
import unittest
from pathlib import Path

from server.app.raw_archive import archive_event, archive_path_for_event


class RawArchiveTests(unittest.TestCase):
    def test_archive_path_is_split_by_website_agent_source_and_day(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "raw_logs"
            event = {
                "event_id": "evt_123",
                "website_id": "../website 1",
                "agent_id": "db/../1",
                "log_type": "",
                "service": "mysql/error",
                "source_id": "src_deadbeefcafebabe",
                "file_path": "/host/var/log/mysql/error.log",
                "timestamp": "2026-07-17T00:01:02+00:00",
                "observed_at": "2026-07-17T00:01:03+00:00",
                "message": "critical error disk full",
            }

            path = archive_path_for_event(root, event)

            self.assertEqual(
                path.relative_to(root).parts,
                (
                    "website_1",
                    "db_1",
                    "mysql_error--src_deadbeefca",
                    "2026-07-17.jsonl",
                ),
            )

    def test_archive_event_appends_compact_jsonl_row(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "raw_logs"
            event = {
                "event_id": "evt_123",
                "website_id": "website_1",
                "agent_id": "db1",
                "agent_role": "db",
                "log_type": "syslog",
                "service": "system",
                "source_id": "src_syslog123456",
                "file_path": "/host/var/log/syslog",
                "timestamp": "2026-07-17T00:01:02+00:00",
                "observed_at": "2026-07-17T00:01:03+00:00",
                "severity": "critical",
                "category": "disk_full",
                "fingerprint": "fp_system_disk_full",
                "message": "critical error disk full",
                "metadata": {"line_number": 10},
            }

            path = archive_event(root, event)

            rows = path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(len(rows), 1)
            stored = json.loads(rows[0])
            self.assertEqual(stored["event_id"], "evt_123")
            self.assertEqual(stored["website_id"], "website_1")
            self.assertEqual(stored["agent_id"], "db1")
            self.assertEqual(stored["source_id"], "src_syslog123456")
            self.assertEqual(stored["file_path"], "/host/var/log/syslog")
            self.assertEqual(stored["message"], "critical error disk full")
            self.assertEqual(stored["metadata"], {"line_number": 10})


if __name__ == "__main__":
    unittest.main()
