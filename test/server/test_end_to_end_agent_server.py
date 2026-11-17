from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SERVER_ROOT = PROJECT_ROOT / "server"
AGENT_ROOT = PROJECT_ROOT / "agent"


class AgentServerEndToEndTests(unittest.TestCase):
    def test_agent_discovers_log_source_then_sends_new_problem_event_to_server(self):
        go = _which("go")
        if not go:
            self.skipTest("go is not available")

        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            port = _free_port()
            data_dir = temp / "data"
            state_dir = temp / "state"
            host_log_root = temp / "host" / "var" / "log"
            nginx_dir = host_log_root / "nginx"
            nginx_dir.mkdir(parents=True)
            error_log = nginx_dir / "error.log"
            error_log.write_text("2026-07-17T00:00:00Z nginx boot ok\n", encoding="utf-8")

            agent_binary = temp / ("ai-log-agent.exe" if os.name == "nt" else "ai-log-agent")
            _run([go, "build", "-o", str(agent_binary), "."], cwd=AGENT_ROOT)

            server = _start_server(port, data_dir)
            try:
                base_url = f"http://127.0.0.1:{port}"
                _wait_for_health(base_url)

                config_path = temp / "agent.yaml"
                config_path.write_text(
                    f"""
server:
  url: "{base_url}"
enrollment:
  token: "install-token"
agent:
  name: "web-e2e"
  role: "web"
  website_id: "website_e2e"
logs:
  auto_discover: true
  discovery_roots:
    - "{_yaml_path(host_log_root)}"
  discovery_max_files: 20
  paths: []
filter:
  send_only_matched: true
  keywords:
    - "error"
    - "disk full"
runtime:
  state_dir: "{_yaml_path(state_dir)}"
  heartbeat_interval_seconds: 1
""".lstrip(),
                    encoding="utf-8",
                )

                _run([str(agent_binary), "--config", str(config_path), "--once"], cwd=AGENT_ROOT)
                sources = _json_get(f"{base_url}/api/log-sources?website_id=website_e2e")["sources"]
                events_after_first_scan = _json_get(f"{base_url}/api/events/recent")["events"]

                with error_log.open("a", encoding="utf-8") as handle:
                    handle.write("2026-07-17T00:01:00Z critical error disk full on /var/www\n")

                _run([str(agent_binary), "--config", str(config_path), "--once"], cwd=AGENT_ROOT)

                agents = _json_get(f"{base_url}/api/agents")["agents"]
                websites = _json_get(f"{base_url}/api/websites")["websites"]
                events = _json_get(f"{base_url}/api/events/recent")["events"]
                incidents = _json_get(f"{base_url}/api/incidents")["incidents"]
                report = _json_get(f"{base_url}/api/analyze?website_id=website_e2e")
            finally:
                _stop_server(server)

        self.assertEqual(events_after_first_scan, [])
        self.assertEqual([agent["agent_id"] for agent in agents], ["web-e2e"])
        self.assertEqual([website["website_id"] for website in websites], ["website_e2e"])
        self.assertTrue(any(_normalized_path(source["path"]).endswith("nginx/error.log") for source in sources))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["website_id"], "website_e2e")
        self.assertEqual(events[0]["agent_id"], "web-e2e")
        self.assertGreater(events[0]["source_confidence"], 0.0)
        self.assertIn("critical error disk full", events[0]["message"])
        self.assertEqual(len(incidents), 1)
        self.assertEqual(incidents[0]["website_id"], "website_e2e")
        self.assertIn("web-e2e", report["agents_checked"])
        self.assertEqual(report["analysis_window_minutes"], 30)


def _which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate)
        if os.name == "nt":
            candidate_exe = Path(directory) / f"{name}.exe"
            if candidate_exe.exists():
                return str(candidate_exe)
    return None


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _start_server(port: int, data_dir: Path) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env.update(
        {
            "AI_LOG_HOST": "127.0.0.1",
            "AI_LOG_PORT": str(port),
            "AI_LOG_DATA_DIR": str(data_dir),
            "AI_LOG_PUBLIC_URL": f"http://127.0.0.1:{port}",
            "ENROLL_TOKEN": "install-token",
            "ENFORCE_AGENT_TOKEN": "true",
            "ADMIN_TOKEN": "",
            "ADMIN_USER": "",
            "ADMIN_PASSWORD": "",
        }
    )
    return subprocess.Popen(
        [sys.executable, "-m", "server.main"],
        cwd=SERVER_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def _stop_server(server: subprocess.Popen[str]) -> None:
    server.terminate()
    try:
        server.wait(timeout=10)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=10)
    if server.stdout:
        server.stdout.close()


def _wait_for_health(base_url: str) -> None:
    deadline = time.time() + 15
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            if _json_get(f"{base_url}/health") == {"status": "ok"}:
                return
        except Exception as exc:  # noqa: BLE001 - helper keeps last startup error for diagnostics.
            last_error = exc
            time.sleep(0.2)
    raise AssertionError(f"server did not become healthy: {last_error}")


def _json_get(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def _run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, timeout=45)
    if result.returncode != 0:
        raise AssertionError(
            f"command failed: {args}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _yaml_path(path: Path) -> str:
    return str(path).replace("\\", "/")


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/")
