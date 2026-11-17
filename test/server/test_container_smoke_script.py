from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ContainerSmokeScriptTests(unittest.TestCase):
    def test_release_container_smoke_script_exercises_server_agent_flow(self):
        script_path = PROJECT_ROOT / "scripts" / "container_smoke.py"

        self.assertTrue(script_path.exists())
        script = script_path.read_text(encoding="utf-8")

        for expected in [
            "AI Log Monitor container smoke",
            "--runtime",
            "--ingest-mode",
            "podman",
            "docker",
            "server/Containerfile",
            "server/gateway/Containerfile",
            "agent/Containerfile",
            "ai-log-smoke-server",
            "ai-log-smoke-gateway",
            "ai-log-smoke-agent",
            "ai-log-smoke-net",
            "website_smoke",
            "nginx/error.log",
            "app-smoke:8080",
            "/api/log-sources?website_id=website_smoke",
            "/api/topology-hints?website_id=website_smoke",
            "/api/agents",
            "/api/incidents",
            "health_status",
            "critical error disk full",
            "_prepare_podman_runtime",
            "XDG_RUNTIME_DIR",
            "aardvark-dns",
            "GATEWAY_LISTEN_ADDRESS=:8888",
            "GATEWAY_INGEST_MODE=",
            "PYTHON_BASE_URL=http://",
            "return f\"http://{gateway_name}:8888\"",
            "_published_port",
        ]:
            self.assertIn(expected, script)

    def test_readme_documents_release_container_smoke(self):
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

        self.assertIn("scripts/container_smoke.py", readme)
        self.assertIn("--runtime docker", readme)
        self.assertIn("--runtime podman", readme)


if __name__ == "__main__":
    unittest.main()
