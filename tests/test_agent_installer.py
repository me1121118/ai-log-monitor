import unittest
from pathlib import Path


class AgentInstallerTests(unittest.TestCase):
    def test_install_agent_script_sets_config_and_runs_rootful_podman(self):
        script = Path("install-agent.sh")

        self.assertTrue(script.exists())
        text = script.read_text(encoding="utf-8")

        self.assertIn("--server-url", text)
        self.assertIn("--enroll-token", text)
        self.assertIn("agent/secrets.env", text)
        self.assertIn("agent/agent.yaml", text)
        self.assertIn("podman compose -f agent/compose.yaml up -d --build", text)
        self.assertIn("sudo", text)
        self.assertIn("validate_enroll_token", text)
        self.assertIn("ENROLL_TOKEN must be the real ASCII token", text)


if __name__ == "__main__":
    unittest.main()
