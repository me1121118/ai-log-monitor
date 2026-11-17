import tempfile
import unittest
from pathlib import Path

from server.app.analysis import build_ai_report, load_ai_settings
from server.app.core import classify_event, normalize_event
from server.app.storage import Store


class AiCoreTests(unittest.TestCase):
    def test_load_ai_settings_reads_yaml_and_environment_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai.yaml"
            config_path.write_text(
                """
ai:
  mode: "api"
  provider: "openai_compatible"
  model: "${AI_MODEL}"
analysis:
  max_context_events: 25
learning:
  enabled: true
providers:
  api:
    endpoint: "${AI_ENDPOINT}"
    api_key: "${AI_API_KEY}"
""".strip(),
                encoding="utf-8",
            )

            settings = load_ai_settings(
                config_path,
                env={
                    "AI_MODEL": "gpt-test",
                    "AI_ENDPOINT": "http://127.0.0.1:9999/v1/chat/completions",
                    "AI_API_KEY": "secret-key",
                },
            )

            self.assertEqual(settings["ai"]["mode"], "api")
            self.assertEqual(settings["ai"]["model"], "gpt-test")
            self.assertEqual(settings["analysis"]["max_context_events"], 25)
            self.assertEqual(settings["providers"]["api"]["endpoint"], "http://127.0.0.1:9999/v1/chat/completions")
            self.assertEqual(settings["providers"]["api"]["api_key"], "secret-key")

    def test_rule_based_ai_correlates_web_timeout_with_database_pressure(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store_with_events(
                Path(temp_dir),
                [
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:11+07:00",
                        "message": "upstream timed out while reading response header from upstream",
                    },
                    {
                        "website_id": "website_1",
                        "agent_id": "db01",
                        "agent_role": "db",
                        "timestamp": "2026-07-14T10:32:12+07:00",
                        "message": "too many connections",
                    },
                    {
                        "website_id": "website_2",
                        "agent_id": "web02",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:13+07:00",
                        "message": "permission denied",
                    },
                ],
            )

            report = build_ai_report(store, "website_1", settings=_mock_settings())

            self.assertEqual(report["website_id"], "website_1")
            self.assertEqual(report["mode"], "mock")
            self.assertEqual(set(report["agents_checked"]), {"web01", "db01"})
            self.assertIn("db01", report["root_cause"])
            self.assertIn("too many connections", report["root_cause"])
            self.assertNotIn("web02", " ".join(report["evidence"]))
            self.assertEqual(report["memory_status"], "stored")

    def test_ai_report_uses_time_window_and_skips_unrelated_healthy_agents(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store_with_events(
                Path(temp_dir),
                [
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:00+07:00",
                        "message": "upstream timed out while reading response header from upstream",
                    },
                    {
                        "website_id": "website_1",
                        "agent_id": "db01",
                        "agent_role": "db",
                        "timestamp": "2026-07-14T10:10:00+07:00",
                        "message": "too many connections",
                    },
                    {
                        "website_id": "website_1",
                        "agent_id": "cache01",
                        "agent_role": "cache",
                        "timestamp": "2026-07-14T10:20:00+07:00",
                        "message": "GET /health 200",
                    },
                    {
                        "website_id": "website_1",
                        "agent_id": "old-db",
                        "agent_role": "db",
                        "timestamp": "2026-07-14T09:50:00+07:00",
                        "message": "too many connections old-window-marker",
                    },
                    {
                        "website_id": "website_2",
                        "agent_id": "web02",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:31:00+07:00",
                        "message": "permission denied",
                    },
                ],
            )
            settings = _mock_settings()
            settings["analysis"]["time_window_minutes"] = 30

            report = build_ai_report(store, "website_1", settings=settings)

            self.assertEqual(report["analysis_window_minutes"], 30)
            self.assertEqual(set(report["agents_checked"]), {"web01", "db01"})
            self.assertEqual(report["primary_agent"], "web01")
            self.assertEqual(report["analysis_sequence"], ["web01", "db01"])
            self.assertIn("db01", report["root_cause"])
            self.assertNotIn("old-window-marker", " ".join(report["evidence"]))
            self.assertNotIn("old-db", report["summary"])
            self.assertNotIn("web02", " ".join(report["context_evidence"]))

    def test_ai_memory_is_returned_when_pattern_repeats(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store_with_events(
                Path(temp_dir),
                [
                    {
                        "website_id": "website_1",
                        "agent_id": "db01",
                        "agent_role": "db",
                        "timestamp": "2026-07-14T10:32:12+07:00",
                        "message": "too many connections",
                    }
                ],
            )
            first_report = build_ai_report(store, "website_1", settings=_mock_settings())
            second_report = build_ai_report(store, "website_1", settings=_mock_settings())

            self.assertEqual(first_report["memory_status"], "stored")
            self.assertEqual(second_report["memory_status"], "matched")
            self.assertTrue(second_report["memory_matches"])
            self.assertIn("db_too_many_connections", second_report["memory_matches"][0]["category"])

    def test_api_ai_prompt_redacts_secrets_from_log_messages(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = _store_with_events(
                Path(temp_dir),
                [
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-17T00:00:00+00:00",
                        "message": "disk full password=supersecret token=abc123 Authorization: Bearer live-token-123",
                    }
                ],
            )
            captured = []

            def capture_post(url, headers, payload, timeout):
                captured.append({"url": url, "headers": headers, "payload": payload, "timeout": timeout})
                return {"choices": [{"message": {"content": "redacted report"}}]}

            settings = _api_settings()
            report = build_ai_report(store, "website_1", settings=settings, http_post=capture_post)

            self.assertEqual(report["summary"], "redacted report")
            prompt = captured[0]["payload"]["messages"][0]["content"]
            self.assertNotIn("supersecret", prompt)
            self.assertNotIn("abc123", prompt)
            self.assertNotIn("live-token-123", prompt)
            self.assertIn("[REDACTED]", prompt)


def _store_with_events(temp_dir: Path, events: list[dict]) -> Store:
    store = Store(temp_dir / "database.db")
    store.init()
    for payload in events:
        store.ingest_event(classify_event(normalize_event(payload)))
    return store


def _mock_settings() -> dict:
    return {
        "ai": {"enabled": True, "mode": "mock", "provider": "none", "model": "none"},
        "analysis": {"max_context_events": 100},
        "learning": {"enabled": True, "remember_patterns": True},
        "providers": {},
        "limits": {"timeout_seconds": 1, "max_output_tokens": 1200},
    }


def _api_settings() -> dict:
    settings = _mock_settings()
    settings["ai"] = {"enabled": True, "mode": "api", "provider": "openai_compatible", "model": "gpt-test"}
    settings["providers"] = {
        "api": {
            "endpoint": "http://ai.local/v1/chat/completions",
            "api_key": "provider-secret",
            "model": "gpt-test",
        }
    }
    settings["privacy"] = {
        "redact_before_send": True,
        "redact_fields": ["password", "token", "authorization", "api_key", "secret"],
    }
    return settings


if __name__ == "__main__":
    unittest.main()
