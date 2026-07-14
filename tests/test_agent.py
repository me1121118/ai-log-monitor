import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from pathlib import Path

from agent.client import AgentClient
from agent.config import AgentConfig, LogPath, load_agent_config
from agent.discovery import with_discovered_log_paths
from agent.main import _register
from agent.scanner import scan_once
from server.app.app import create_app


class AgentConfigTests(unittest.TestCase):
    def test_load_agent_config_substitutes_environment_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "agent.yaml"
            config_path.write_text(
                """
server:
  url: "http://127.0.0.1:8888"
enrollment:
  token: "${ENROLL_TOKEN}"
agent:
  name: "web01"
  role: "web"
  website_id: "website_1"
logs:
  paths:
    - name: "app_log"
      path: "/tmp/app.log"
      type: "generic"
filter:
  send_only_matched: true
  keywords:
    - "error"
runtime:
  state_dir: "/state"
""".strip(),
                encoding="utf-8",
            )

            config = load_agent_config(config_path, env={"ENROLL_TOKEN": "install-token"})

            self.assertEqual(config.server_url, "http://127.0.0.1:8888")
            self.assertEqual(config.enroll_token, "install-token")
            self.assertEqual(config.agent_id, "web01")
            self.assertEqual(config.website_id, "website_1")
            self.assertEqual(config.log_paths[0].name, "app_log")
            self.assertEqual(config.keywords, ["error"])


class AgentScannerTests(unittest.TestCase):
    def test_scan_once_reads_auto_discovered_log_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            syslog = temp / "var" / "log" / "syslog"
            syslog.parent.mkdir(parents=True)
            syslog.write_text("normal line\nservice error happened\n", encoding="utf-8")
            state_dir = temp / "state"
            config = AgentConfig(
                server_url="http://127.0.0.1:8888",
                enroll_token="install-token",
                agent_id="web01",
                agent_role="web",
                website_id="website_1",
                log_paths=[],
                send_only_matched=True,
                keywords=[],
                state_dir=state_dir,
                heartbeat_interval_seconds=30,
            )

            discovered = with_discovered_log_paths(
                config,
                candidates=[("syslog", str(syslog), "system")],
            )
            events = scan_once(discovered)

            self.assertEqual([event["message"] for event in events], ["service error happened"])
            self.assertEqual(discovered.log_paths[0].name, "syslog")
            self.assertEqual(discovered.log_paths[0].path, syslog)

    def test_auto_discovery_keeps_configured_paths_and_skips_missing_candidates(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            syslog = temp / "var" / "log" / "syslog"
            missing_nginx = temp / "var" / "log" / "nginx" / "error.log"
            custom_log = temp / "app" / "app.log"
            syslog.parent.mkdir(parents=True)
            custom_log.parent.mkdir(parents=True)
            syslog.write_text("system error\n", encoding="utf-8")
            custom_log.write_text("custom error\n", encoding="utf-8")
            config = AgentConfig(
                server_url="http://127.0.0.1:8888",
                enroll_token="install-token",
                agent_id="web01",
                agent_role="web",
                website_id="website_1",
                log_paths=[LogPath("custom", custom_log, "generic")],
                send_only_matched=True,
                keywords=[],
                state_dir=temp / "state",
                heartbeat_interval_seconds=30,
            )

            discovered = with_discovered_log_paths(
                config,
                candidates=[
                    ("syslog", str(syslog), "system"),
                    ("nginx_error", str(missing_nginx), "nginx"),
                ],
            )

            self.assertEqual([item.name for item in discovered.log_paths], ["custom", "syslog"])
            self.assertEqual([item.path for item in discovered.log_paths], [custom_log, syslog])

    def test_scan_once_skips_log_file_when_permission_is_denied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            protected_log = temp / "syslog"
            protected_log.write_text("service error happened\n", encoding="utf-8")
            config = AgentConfig(
                server_url="http://127.0.0.1:8888",
                enroll_token="install-token",
                agent_id="web01",
                agent_role="web",
                website_id="website_1",
                log_paths=[LogPath("syslog", protected_log, "system")],
                send_only_matched=True,
                keywords=[],
                state_dir=temp / "state",
                heartbeat_interval_seconds=30,
            )

            original_open = Path.open

            def guarded_open(path, *args, **kwargs):
                if path == protected_log:
                    raise PermissionError("denied")
                return original_open(path, *args, **kwargs)

            with patch.object(Path, "open", guarded_open):
                events = scan_once(config)

            self.assertEqual(events, [])
            self.assertEqual((temp / "state" / "offsets.json").read_text(encoding="utf-8"), "{}")

    def test_scan_once_sends_only_new_matched_lines_and_persists_offset(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            log_path = temp / "app.log"
            state_dir = temp / "state"
            config_path = temp / "agent.yaml"
            log_path_for_config = str(log_path).replace("\\", "/")
            state_dir_for_config = str(state_dir).replace("\\", "/")
            log_path.write_text("GET /health 200\nupstream timed out\n", encoding="utf-8")
            config_path.write_text(
                f"""
server:
  url: "http://127.0.0.1:8888"
enrollment:
  token: "install-token"
agent:
  name: "web01"
  role: "web"
  website_id: "website_1"
logs:
  paths:
    - name: "app_log"
      path: "{log_path_for_config}"
      type: "generic"
filter:
  send_only_matched: true
  keywords:
    - "timed out"
runtime:
  state_dir: "{state_dir_for_config}"
""".strip(),
                encoding="utf-8",
            )
            config = load_agent_config(config_path, env={})

            first_events = scan_once(config)
            second_events = scan_once(config)
            with log_path.open("a", encoding="utf-8") as log_file:
                log_file.write("database timeout\n")
            third_events = scan_once(config)

            self.assertEqual([event["message"] for event in first_events], ["upstream timed out"])
            self.assertEqual(second_events, [])
            self.assertEqual([event["message"] for event in third_events], ["database timeout"])
            self.assertTrue((state_dir / "offsets.json").exists())


class AgentHttpTests(unittest.TestCase):
    def test_agent_register_payload_includes_website_id_from_config(self):
        config = AgentConfig(
            server_url="http://127.0.0.1:8888",
            enroll_token="install-token",
            agent_id="web01",
            agent_role="web",
            website_id="website_1",
            log_paths=[],
            send_only_matched=True,
            keywords=[],
            state_dir=Path("/state"),
            heartbeat_interval_seconds=30,
        )
        client = _CaptureRegisterClient()

        token = _register(config, client)

        self.assertEqual(token, "agt_test")
        self.assertEqual(client.enroll_token, "install-token")
        self.assertEqual(client.payload["agent_id"], "web01")
        self.assertEqual(client.payload["website_id"], "website_1")

    def test_agent_registers_and_posts_problem_event_to_server(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir), enroll_token="install-token")
            server = _start_test_server(app)
            try:
                client = AgentClient(f"http://127.0.0.1:{server.server_port}")

                register_result = client.register(
                    "install-token",
                    {
                        "agent_id": "web01",
                        "agent_role": "web",
                        "hostname": "web01.local",
                        "source_ip": "10.1.0.21",
                    },
                )
                ingest_result = client.ingest(
                    register_result["agent_token"],
                    {
                        "website_id": "website_1",
                        "agent_id": "web01",
                        "agent_role": "web",
                        "timestamp": "2026-07-14T10:32:11+07:00",
                        "status_code": 502,
                        "message": "upstream timed out while reading response header from upstream",
                    },
                )

                self.assertEqual(register_result["status"], "active")
                self.assertEqual(ingest_result["severity"], "problem")
                self.assertIsNotNone(ingest_result["incident_id"])
            finally:
                server.shutdown()
                server.server_close()


class _CaptureRegisterClient:
    def __init__(self):
        self.enroll_token = ""
        self.payload = {}

    def register(self, enroll_token, payload):
        self.enroll_token = enroll_token
        self.payload = payload
        return {"agent_token": "agt_test"}


def _start_test_server(app):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            status, headers, body = app.handle_json("GET", self.path, dict(self.headers), b"")
            self._send(status, headers, body)

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length)
            status, headers, response = app.handle_json("POST", self.path, dict(self.headers), body)
            self._send(status, headers, response)

        def log_message(self, format, *args):
            return

        def _send(self, status, headers, body):
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


if __name__ == "__main__":
    unittest.main()
