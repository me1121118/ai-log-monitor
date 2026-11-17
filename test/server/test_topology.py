import json
import tempfile
import unittest
from pathlib import Path

from server.app.analysis import build_ai_report
from server.app.app import create_app
from server.app.core import classify_event, normalize_event
from server.app.storage import Store


class TopologyStoreTests(unittest.TestCase):
    def test_topology_hints_are_website_isolated_and_updateable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()

            first = store.upsert_topology_hint(
                {
                    "website_id": "website_1",
                    "agent_id": "web01",
                    "source": "/host/etc/nginx/site.conf",
                    "hint_type": "http_upstream",
                    "target": "app01:8080",
                    "confidence": 0.86,
                    "last_seen_at": "2026-07-17T00:00:00+00:00",
                    "metadata": {"directive": "proxy_pass"},
                }
            )
            store.upsert_topology_hint(
                {
                    "website_id": "website_2",
                    "agent_id": "web99",
                    "source": "/host/etc/nginx/site.conf",
                    "hint_type": "http_upstream",
                    "target": "app99:8080",
                    "confidence": 0.86,
                    "last_seen_at": "2026-07-17T00:00:00+00:00",
                }
            )
            updated = store.upsert_topology_hint(
                {
                    "website_id": "website_1",
                    "agent_id": "web01",
                    "source": "/host/etc/nginx/site.conf",
                    "hint_type": "http_upstream",
                    "target": "app01:8080",
                    "confidence": 0.94,
                    "last_seen_at": "2026-07-17T00:05:00+00:00",
                    "metadata": {"directive": "proxy_pass", "line": 12},
                }
            )

            hints = store.list_topology_hints("website_1")

            self.assertEqual(first["target"], "app01:8080")
            self.assertEqual(updated["confidence"], 0.94)
            self.assertEqual(len(hints), 1)
            self.assertEqual(hints[0]["website_id"], "website_1")
            self.assertEqual(hints[0]["agent_id"], "web01")
            self.assertEqual(hints[0]["metadata"]["line"], 12)


class TopologyHttpAndAiTests(unittest.TestCase):
    def test_topology_hint_api_feeds_dashboard_and_ai_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            payload = {
                "website_id": "website_1",
                "agent_id": "web01",
                "hints": [
                    {
                        "source": "/host/etc/nginx/site.conf",
                        "hint_type": "http_upstream",
                        "target": "app01:8080",
                        "confidence": 0.9,
                        "last_seen_at": "2026-07-17T00:00:00+00:00",
                        "metadata": {"directive": "proxy_pass"},
                    }
                ],
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/topology-hints",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            list_status, _list_headers, list_body = app.handle_json(
                "GET",
                "/api/topology-hints?website_id=website_1",
                {},
                b"",
            )
            event = classify_event(
                normalize_event(
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-17T00:01:00+00:00",
                        "message": "connect() failed (111: connection refused) while connecting to upstream",
                    }
                )
            )
            app.store.ingest_event(event)
            captured: dict[str, str] = {}

            def fake_post(_url, _headers, payload, _timeout):
                captured["prompt"] = payload["messages"][0]["content"]
                return {"choices": [{"message": {"content": "AI saw topology"}}]}

            report = build_ai_report(
                app.store,
                "website_1",
                settings={
                    "ai": {"enabled": True, "mode": "api", "provider": "api", "model": "test"},
                    "providers": {"api": {"endpoint": "http://ai.local/v1/chat", "api_key": "k", "model": "test"}},
                    "analysis": {"max_context_events": 20, "time_window_minutes": 30},
                    "learning": {"enabled": False, "remember_patterns": False},
                    "notifications": {"enabled": False},
                    "privacy": {"redact_before_send": True, "redact_fields": []},
                    "limits": {"timeout_seconds": 1},
                },
                http_post=fake_post,
            )
            html = app.dashboard_html(selected_website_id="website_1", page="website").decode("utf-8")

            response = json.loads(body.decode("utf-8"))
            listed = json.loads(list_body.decode("utf-8"))["hints"]
            self.assertEqual(status, 201)
            self.assertEqual(response["stored"], 1)
            self.assertEqual(list_status, 200)
            self.assertEqual(listed[0]["target"], "app01:8080")
            self.assertIn("Topology Hints", html)
            self.assertIn("app01:8080", html)
            self.assertIn("Topology hints", captured["prompt"])
            self.assertIn("web01 -> app01:8080", captured["prompt"])
            self.assertEqual(report["summary"], "AI saw topology")


if __name__ == "__main__":
    unittest.main()
