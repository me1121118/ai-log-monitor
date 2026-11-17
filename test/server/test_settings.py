import json
import tempfile
import unittest
from pathlib import Path

from server.app.analysis import load_ai_settings
from server.app.app import create_app


class SettingsApiTests(unittest.TestCase):
    def test_settings_api_reads_current_ai_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai.yaml"
            config_path.write_text(
                """
ai:
  enabled: true
  mode: "api"
  provider: "openai_compatible"
  model: "gpt-test"
analysis:
  auto_analyze: true
  auto_analyze_min_severity: "critical"
  time_window_minutes: 45
  max_context_events: 200
notifications:
  enabled: true
  language: "th"
  line_webhook_url: "http://notify.local/line"
  google_chat_webhook_url: "http://notify.local/google-chat"
providers:
  api:
    endpoint: "http://ai.local/v1/chat/completions"
    api_key: "secret"
    model: "gpt-test"
""".strip(),
                encoding="utf-8",
            )
            app = create_app(Path(temp_dir), ai_config_path=config_path)

            status, _headers, body = app.handle_json("GET", "/api/settings", {}, b"")

            payload = json.loads(body.decode("utf-8"))
            self.assertEqual(status, 200)
            self.assertEqual(payload["settings"]["ai"]["mode"], "api")
            self.assertEqual(payload["settings"]["analysis"]["time_window_minutes"], 45)
            self.assertEqual(payload["settings"]["notifications"]["line_webhook_url"], "http://notify.local/line")
            self.assertEqual(payload["settings"]["providers"]["api"]["endpoint"], "http://ai.local/v1/chat/completions")

    def test_settings_api_persists_analysis_and_notification_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai.yaml"
            app = create_app(Path(temp_dir), ai_config_path=config_path)
            requested = {
                "ai": {
                    "enabled": True,
                    "mode": "api",
                    "provider": "openai_compatible",
                    "model": "gpt-4.1-mini",
                },
                "analysis": {
                    "auto_analyze": True,
                    "auto_analyze_min_severity": "critical",
                    "time_window_minutes": 30,
                    "max_context_events": 150,
                },
                "notifications": {
                    "enabled": True,
                    "language": "th",
                    "line_webhook_url": "https://line.example/hook",
                    "google_chat_webhook_url": "https://chat.example/hook",
                },
                "providers": {
                    "api": {
                        "endpoint": "https://ai.example/v1/chat/completions",
                        "api_key": "saved-key",
                        "model": "gpt-4.1-mini",
                    }
                },
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/settings",
                {},
                json.dumps(requested).encode("utf-8"),
            )

            response = json.loads(body.decode("utf-8"))
            reloaded = load_ai_settings(config_path)
            self.assertEqual(status, 200)
            self.assertEqual(response["settings"]["analysis"]["time_window_minutes"], 30)
            self.assertEqual(reloaded["ai"]["mode"], "api")
            self.assertEqual(reloaded["analysis"]["max_context_events"], 150)
            self.assertEqual(reloaded["notifications"]["google_chat_webhook_url"], "https://chat.example/hook")
            self.assertEqual(reloaded["providers"]["api"]["endpoint"], "https://ai.example/v1/chat/completions")

    def test_settings_page_renders_current_values_and_save_form(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "ai.yaml"
            config_path.write_text(
                """
ai:
  enabled: true
  mode: "api"
  provider: "openai_compatible"
  model: "gpt-test"
analysis:
  auto_analyze: true
  auto_analyze_min_severity: "critical"
  time_window_minutes: 30
notifications:
  enabled: true
  language: "th"
  line_webhook_url: "https://line.example/hook"
  google_chat_webhook_url: "https://chat.example/hook"
providers:
  api:
    endpoint: "https://ai.example/v1/chat/completions"
    api_key: ""
    model: "gpt-test"
""".strip(),
                encoding="utf-8",
            )
            app = create_app(Path(temp_dir), ai_config_path=config_path)

            html = app.dashboard_html(page="settings").decode("utf-8")

            self.assertIn('id="settings-form"', html)
            self.assertIn('name="analysis.time_window_minutes"', html)
            self.assertIn('value="30"', html)
            self.assertIn('name="notifications.line_webhook_url"', html)
            self.assertIn("https://line.example/hook", html)
            self.assertIn("Google Chat", html)

    def test_dashboard_script_wires_settings_save_form(self):
        js_path = Path(__file__).resolve().parents[2] / "server" / "server" / "app" / "static" / "js" / "dashboard.js"
        js = js_path.read_text(encoding="utf-8")

        self.assertIn("settings-form", js)
        self.assertIn("/api/settings", js)
        self.assertIn("setNestedValue", js)


if __name__ == "__main__":
    unittest.main()
