from pathlib import Path
import unittest


class LocalManageScriptTests(unittest.TestCase):
    SERVER_ROOT = Path(__file__).resolve().parents[2] / "server"

    def test_manage_script_exposes_local_control_actions(self):
        script_path = self.SERVER_ROOT / "manage.ps1"

        self.assertTrue(script_path.exists())
        script = script_path.read_text(encoding="utf-8")

        for expected in [
            "ValidateSet('Start','Stop','Restart','Status','Test','Open','Clean','Backup','Restore','Update','Doctor')",
            "server\\secrets.env",
            "server.pid",
            "Get-NetTCPConnection",
            "Start-Process",
            "python -m unittest discover -s ../test/server -v",
            "Invoke-ServerBackup",
            "Invoke-ServerRestore",
            "Invoke-ServerUpdate",
            "Invoke-ServerDoctor",
            "server.app.maintenance",
        ]:
            self.assertIn(expected, script)

    def test_linux_manage_script_exposes_podman_lifecycle_backup_and_update(self):
        script_path = self.SERVER_ROOT / "manage.sh"

        self.assertTrue(script_path.exists())
        script = script_path.read_text(encoding="utf-8")

        for expected in [
            "Usage: ./manage.sh {start|stop|restart|status|test|backup|restore|update|open|clean|doctor}",
            "podman compose",
            "docker compose",
            "server.app.maintenance",
            "backup_server",
            "restore_server",
            "update_server",
            "doctor_server",
            "AI Log Monitor server doctor",
            "data dir writable",
            "python_cmd",
            "python3",
            '(cd "$ROOT" && "$PYTHON" -m server.app.maintenance backup',
            '(cd "$ROOT" && "$PYTHON" -m server.app.maintenance restore',
            "compose.yaml",
            "health",
        ]:
            self.assertIn(expected, script)

    def test_linux_manage_script_does_not_source_secret_env_as_shell(self):
        script = (self.SERVER_ROOT / "manage.sh").read_text(encoding="utf-8")

        self.assertNotIn("set -a", script)
        self.assertNotIn('. "$SECRETS_FILE"', script)


if __name__ == "__main__":
    unittest.main()
