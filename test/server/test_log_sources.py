import json
import tempfile
import unittest
from pathlib import Path

from server.app.app import create_app
from server.app.storage import Store


class LogSourceRegistryTests(unittest.TestCase):
    def test_upsert_log_source_is_website_isolated_and_updates_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()

            first = store.upsert_log_source(
                {
                    "website_id": "website_1",
                    "agent_id": "app01",
                    "source_id": "src_app01_var_log_app",
                    "name": "app log",
                    "path": "/var/log/myapp/app.log",
                    "source_type": "custom_app",
                    "service": "myapp",
                    "classification": "custom_app",
                    "confidence": 0.71,
                    "status": "readable",
                    "last_seen_at": "2026-07-17T00:00:00+00:00",
                    "metadata": {"reason": "process_reference"},
                }
            )
            store.upsert_log_source(
                {
                    "website_id": "website_2",
                    "agent_id": "app02",
                    "source_id": "src_app02_var_log_app",
                    "name": "app log",
                    "path": "/var/log/myapp/app.log",
                    "source_type": "custom_app",
                    "service": "myapp",
                    "classification": "custom_app",
                    "confidence": 0.68,
                    "status": "readable",
                    "last_seen_at": "2026-07-17T00:00:00+00:00",
                    "metadata": {},
                }
            )
            updated = store.upsert_log_source(
                {
                    "website_id": "website_1",
                    "agent_id": "app01",
                    "source_id": "src_app01_var_log_app",
                    "name": "app log",
                    "path": "/var/log/myapp/app.log",
                    "source_type": "custom_app",
                    "service": "myapp",
                    "classification": "custom_app",
                    "confidence": 0.91,
                    "status": "unreadable",
                    "last_seen_at": "2026-07-17T00:05:00+00:00",
                    "metadata": {"error": "permission denied"},
                }
            )

            sources = store.list_log_sources("website_1")

            self.assertEqual(first["source_id"], "src_app01_var_log_app")
            self.assertEqual(updated["status"], "unreadable")
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["website_id"], "website_1")
            self.assertEqual(sources[0]["agent_id"], "app01")
            self.assertEqual(sources[0]["confidence"], 0.91)
            self.assertEqual(sources[0]["metadata"]["error"], "permission denied")


class LogSourceHttpTests(unittest.TestCase):
    def test_log_source_api_upserts_and_lists_sources_by_website(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            payload = {
                "website_id": "website_1",
                "agent_id": "app01",
                "sources": [
                    {
                        "source_id": "src_app01_custom",
                        "name": "custom app",
                        "path": "/opt/shop/logs/app.log",
                        "source_type": "custom_app",
                        "service": "shop",
                        "classification": "custom_app",
                        "confidence": 0.82,
                        "status": "readable",
                        "last_seen_at": "2026-07-17T00:00:00+00:00",
                        "metadata": {"reason": "bounded_app_path"},
                    }
                ],
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/log-sources",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            list_status, _list_headers, list_body = app.handle_json(
                "GET",
                "/api/log-sources?website_id=website_1",
                {},
                b"",
            )

            response = json.loads(body.decode("utf-8"))
            sources = json.loads(list_body.decode("utf-8"))["sources"]
            self.assertEqual(status, 201)
            self.assertEqual(response["stored"], 1)
            self.assertEqual(list_status, 200)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["source_id"], "src_app01_custom")
            self.assertEqual(sources[0]["metadata"]["reason"], "bounded_app_path")

    def test_log_source_report_replaces_removed_sources_for_same_agent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))

            def source(source_id: str, path: str) -> dict:
                return {
                    "source_id": source_id,
                    "name": source_id,
                    "path": path,
                    "source_type": "database",
                    "service": "mariadb",
                    "classification": "database",
                    "confidence": 0.9,
                    "status": "readable",
                    "last_seen_at": "2026-07-19T00:00:00+00:00",
                    "metadata": {},
                }

            first_report = {
                "website_id": "website_1",
                "agent_id": "db1",
                "sources": [
                    source("mariadb", "/host/var/log/mysql/error.log"),
                    source("unused", "/host/var/log/apt/history.log"),
                ],
            }
            second_report = {
                "website_id": "website_1",
                "agent_id": "db1",
                "sources": [source("mariadb", "/host/var/log/mysql/error.log")],
            }

            app.handle_json("POST", "/api/log-sources", {}, json.dumps(first_report).encode())
            app.handle_json("POST", "/api/log-sources", {}, json.dumps(second_report).encode())
            _status, _headers, body = app.handle_json(
                "GET", "/api/log-sources?website_id=website_1", {}, b""
            )

            sources = json.loads(body.decode())["sources"]
            self.assertEqual([item["source_id"] for item in sources], ["mariadb"])


if __name__ == "__main__":
    unittest.main()
