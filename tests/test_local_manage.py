from pathlib import Path
import unittest


class LocalManageScriptTests(unittest.TestCase):
    def test_manage_script_exposes_local_control_actions(self):
        project_root = Path(__file__).resolve().parents[1]
        script_path = project_root / "manage.ps1"

        self.assertTrue(script_path.exists())
        script = script_path.read_text(encoding="utf-8")

        for expected in [
            "ValidateSet('Start','Stop','Restart','Status','Test','Open','Clean')",
            "server\\secrets.env",
            "server.pid",
            "Get-NetTCPConnection",
            "Start-Process",
            "python -m unittest discover -s tests -v",
        ]:
            self.assertIn(expected, script)


if __name__ == "__main__":
    unittest.main()
