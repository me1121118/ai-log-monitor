from pathlib import Path
import shutil
import subprocess
import unittest


class AgentInstallerTests(unittest.TestCase):
    AGENT_ROOT = Path(__file__).resolve().parents[2] / "agent"

    def test_install_agent_script_sets_config_and_runs_rootful_podman(self):
        script = self.AGENT_ROOT / "install-agent.sh"

        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        self.assertIn("--server-url", text)
        self.assertIn("--enroll-token", text)
        self.assertIn("--dry-run", text)
        self.assertIn("--doctor", text)
        self.assertIn("--no-systemd", text)
        self.assertIn("secrets.env", text)
        self.assertIn("agent.yaml", text)
        self.assertIn("detect_compose", text)
        self.assertIn("write_systemd_service", text)
        self.assertIn("ai-log-monitor-agent.service", text)
        self.assertIn("systemctl enable ai-log-monitor-agent.service", text)
        self.assertIn("systemctl list-units", text)
        self.assertIn("compose -f compose.yaml up -d --build", text)
        self.assertIn("sudo", text)
        self.assertIn("validate_enroll_token", text)
        self.assertIn("ENROLL_TOKEN must be the real ASCII token", text)
        self.assertIn("doctor_agent", text)
        self.assertIn("AI Log Monitor agent doctor", text)
        self.assertIn("server health", text)

    def test_install_agent_help_uses_current_example_server_url(self):
        script = self.AGENT_ROOT / "install-agent.sh"
        text = script.read_text(encoding="utf-8")

        self.assertIn("--server-url http://10.1.0.10:8888", text)
        self.assertNotIn("10.1.15.180", text)

    def test_compose_mounts_all_default_host_discovery_roots(self):
        compose = (self.AGENT_ROOT / "compose.yaml").read_text(encoding="utf-8")

        self.assertIn("/var/log:/host/var/log:ro", compose)
        self.assertIn("/etc:/host/etc:ro", compose)
        self.assertIn("/opt:/host/opt:ro", compose)
        self.assertIn("/srv:/host/srv:ro", compose)

    def test_default_config_enables_automatic_log_discovery(self):
        for config_path in [
            self.AGENT_ROOT / "agent.yaml",
            self.AGENT_ROOT / "config-templates" / "agent.yaml",
        ]:
            text = config_path.read_text(encoding="utf-8")
            self.assertIn("auto_discover: true", text)
            self.assertNotIn("auto_discover: false", text)

    def test_install_agent_dry_run_parses_required_options_without_writing_token(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is not available")

        project_root = self.AGENT_ROOT
        script_path = project_root / "install-agent.sh"

        result = subprocess.run(
            [
                bash,
                _bash_path(script_path),
                "--dry-run",
                "--server-url",
                "http://10.1.0.10:8888",
                "--enroll-token",
                "real-token",
                "--name",
                "web1",
                "--role",
                "web",
                "--website-id",
                "website_1",
            ],
            cwd=project_root,
            text=True,
            capture_output=True,
            timeout=15,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("server: http://10.1.0.10:8888", result.stdout)
        self.assertIn("agent:  web1 (web)", result.stdout)
        self.assertIn("group:  website_1", result.stdout)
        self.assertIn("enroll token: configured", result.stdout.lower())
        self.assertIn("systemd: enabled", result.stdout.lower())
        self.assertNotIn("real-token", result.stdout)


if __name__ == "__main__":
    unittest.main()


def _bash_path(path: Path) -> str:
    text = str(path)
    if len(text) >= 3 and text[1:3] == ":\\":
        drive = text[0].lower()
        return f"/mnt/{drive}/" + text[3:].replace("\\", "/")
    return text
