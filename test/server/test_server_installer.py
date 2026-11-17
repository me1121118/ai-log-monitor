from pathlib import Path
import shutil
import subprocess
import unittest


class ServerInstallerTests(unittest.TestCase):
    def test_install_server_script_exposes_safe_linux_install_flow(self):
        project_root = Path(__file__).resolve().parents[2] / "server"
        script_path = project_root / "install-server.sh"

        self.assertTrue(script_path.exists())
        script = script_path.read_text(encoding="utf-8")

        for expected in [
            "Usage: ./install-server.sh",
            "--public-url",
            "--admin-user",
            "--admin-password",
            "--enroll-token",
            "--line-webhook-url",
            "--google-chat-webhook-url",
            "--no-start",
            "--no-systemd",
            "--dry-run",
            "write_secrets",
            "write_server_config",
            "write_ai_config",
            "write_systemd_service",
            "ai-log-monitor-server.service",
            "systemctl enable ai-log-monitor-server.service",
            "systemctl list-units",
            "random_token",
            "chmod 600 \"$SECRETS_FILE\"",
            "./manage.sh start",
        ]:
            self.assertIn(expected, script)

    def test_install_server_dry_run_parses_required_options_without_writing(self):
        bash = shutil.which("bash")
        if not bash:
            self.skipTest("bash is not available")
        project_root = Path(__file__).resolve().parents[2] / "server"
        script_path = project_root / "install-server.sh"
        script_arg = _bash_path(script_path)

        result = subprocess.run(
            [
                bash,
                script_arg,
                "--dry-run",
                "--public-url",
                "http://10.1.0.10:8888",
                "--admin-user",
                "admin",
                "--admin-password",
                "strong-password",
                "--admin-token",
                "admin-token",
                "--enroll-token",
                "install-token",
                "--line-webhook-url",
                "https://line.example/hook",
                "--google-chat-webhook-url",
                "https://chat.example/hook",
            ],
            cwd=project_root,
            text=True,
            capture_output=True,
            timeout=15,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DRY RUN", result.stdout)
        self.assertIn("http://10.1.0.10:8888", result.stdout)
        self.assertIn("line webhook: configured", result.stdout.lower())
        self.assertIn("systemd: enabled", result.stdout.lower())
        self.assertNotIn("strong-password", result.stdout)


if __name__ == "__main__":
    unittest.main()


def _bash_path(path: Path) -> str:
    text = str(path)
    if len(text) >= 3 and text[1:3] == ":\\":
        drive = text[0].lower()
        return f"/mnt/{drive}/" + text[3:].replace("\\", "/")
    return text
