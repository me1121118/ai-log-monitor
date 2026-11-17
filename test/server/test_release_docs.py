from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ReleaseDocsTests(unittest.TestCase):
    def test_root_readme_explains_server_agent_install_and_dashboard_flow(self):
        readme = PROJECT_ROOT / "README.md"

        self.assertTrue(readme.exists())
        text = readme.read_text(encoding="utf-8")

        for expected in [
            "AI Log Monitor",
            "server/install-server.sh",
            "agent/install-agent.sh",
            "server/manage.sh",
            "server/manage.ps1",
            "server/manage.sh doctor",
            "manage.ps1 -Action Doctor",
            "agent/install-agent.sh --doctor",
            "systemctl status ai-log-monitor-server.service",
            "systemctl status ai-log-monitor-agent.service",
            "Websites -> Website -> Machines -> Logs",
            "LINE_WEBHOOK_URL",
            "GOOGLE_CHAT_WEBHOOK_URL",
            "Do not put real tokens in chat",
            "/api/system/health",
            "health_status",
            "Incident memory is not deleted by event retention",
        ]:
            self.assertIn(expected, text)


if __name__ == "__main__":
    unittest.main()
