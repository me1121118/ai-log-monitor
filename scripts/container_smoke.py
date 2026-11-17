#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SERVER_CONTAINERFILE = PROJECT_ROOT / "server" / "Containerfile"  # server/Containerfile
GATEWAY_CONTAINERFILE = PROJECT_ROOT / "server" / "gateway" / "Containerfile"  # server/gateway/Containerfile
AGENT_CONTAINERFILE = PROJECT_ROOT / "agent" / "Containerfile"  # agent/Containerfile


def main() -> int:
    parser = argparse.ArgumentParser(description="AI Log Monitor container smoke")
    parser.add_argument("--runtime", choices=["auto", "docker", "podman"], default="auto")
    parser.add_argument("--keep", action="store_true", help="Keep temporary files and containers for inspection.")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--ingest-mode", choices=["shadow", "evidence"], default="shadow")
    args = parser.parse_args()

    runtime = _detect_runtime(args.runtime)
    _prepare_podman_runtime(runtime)
    run_id = f"{os.getpid()}-{int(time.time())}"
    temp_root = Path(tempfile.mkdtemp(prefix="ai-log-smoke-"))
    server_image = f"ai-log-smoke-server:{run_id}"
    gateway_image = f"ai-log-smoke-gateway:{run_id}"
    agent_image = f"ai-log-smoke-agent:{run_id}"
    server_name = f"ai-log-smoke-server-{run_id}"
    gateway_name = f"ai-log-smoke-gateway-{run_id}"
    agent_name = f"ai-log-smoke-agent-{run_id}"
    network_name = f"ai-log-smoke-net-{run_id}"
    published_port = _free_port()
    summary: dict[str, Any] = {"runtime": runtime, "temp_root": str(temp_root)}

    try:
        print(f"AI Log Monitor container smoke using {runtime}")
        _run([runtime, "build", "-t", server_image, "-f", str(SERVER_CONTAINERFILE), str(PROJECT_ROOT / "server")], args.timeout)
        _run([runtime, "build", "-t", gateway_image, "-f", str(GATEWAY_CONTAINERFILE), str(PROJECT_ROOT / "server" / "gateway")], args.timeout)
        _run([runtime, "build", "-t", agent_image, "-f", str(AGENT_CONTAINERFILE), str(PROJECT_ROOT / "agent")], args.timeout)
        if network_name:
            _run([runtime, "network", "create", network_name], args.timeout)

        data_dir = temp_root / "server-data"
        state_dir = temp_root / "agent-state"
        host_log_root = temp_root / "host" / "var" / "log"
        host_etc_root = temp_root / "host" / "etc"
        nginx_dir = host_log_root / "nginx"
        nginx_conf_dir = host_etc_root / "nginx" / "conf.d"
        data_dir.mkdir(parents=True)
        state_dir.mkdir(parents=True)
        nginx_dir.mkdir(parents=True)
        nginx_conf_dir.mkdir(parents=True)
        error_log = nginx_dir / "error.log"
        error_log.write_text("2026-07-17T00:00:00Z nginx boot ok\n", encoding="utf-8")
        (nginx_conf_dir / "site.conf").write_text(
            "location /api { proxy_pass http://app-smoke:8080; }\n",
            encoding="utf-8",
        )

        server_url = f"http://127.0.0.1:{published_port}"
        server_args = [
                runtime,
                "run",
                "-d",
                "--name",
                server_name,
                "-e",
                "AI_LOG_HOST=0.0.0.0",
                "-e",
                "AI_LOG_PORT=8889",
                "-e",
                "AI_LOG_DATA_DIR=/data",
                "-e",
                "AI_LOG_PUBLIC_URL=http://127.0.0.1:8888",
                "-e",
                "ENROLL_TOKEN=install-token",
                "-e",
                "ENFORCE_AGENT_TOKEN=true",
                "-e",
                "GATEWAY_INTERNAL_TOKEN=gateway-smoke-token",
                "-e",
                "ADMIN_TOKEN=",
                "-e",
                "ADMIN_USER=",
                "-e",
                "ADMIN_PASSWORD=",
                "-v",
                _volume(data_dir, "/data", runtime),
                server_image,
        ]
        if network_name:
            server_args[5:5] = ["--network", network_name]
        _run(server_args, args.timeout)

        gateway_args = [
                runtime,
                "run",
                "-d",
                "--name",
                gateway_name,
                "-e",
                "GATEWAY_LISTEN_ADDRESS=:8888",
                "-e",
                f"PYTHON_BASE_URL=http://{server_name}:8889",
                "-e",
                f"GATEWAY_INGEST_MODE={args.ingest_mode}",
                "-e",
                "GATEWAY_INTERNAL_TOKEN=gateway-smoke-token",
                "-p",
                _published_port(runtime, published_port),
                gateway_image,
        ]
        if network_name:
            gateway_args[5:5] = ["--network", network_name]
        _run(gateway_args, args.timeout)
        _wait_for_health(server_url, args.timeout)

        config_path = temp_root / "agent.yaml"
        config_path.write_text(
            f"""
server:
  url: "{_agent_server_url(runtime, gateway_name, published_port)}"
enrollment:
  token: "${{ENROLL_TOKEN}}"
agent:
  name: "web-smoke"
  role: "web"
  website_id: "website_smoke"
logs:
  auto_discover: true
  discovery_roots:
    - "/host/var/log"
    - "/host/etc"
  discovery_max_files: 20
  paths: []
filter:
  send_only_matched: {str(args.ingest_mode != "evidence").lower()}
  keywords:
    - "error"
    - "disk full"
runtime:
  state_dir: "/state"
  heartbeat_interval_seconds: 1
""".lstrip(),
            encoding="utf-8",
        )

        _run_agent_once(
            runtime,
            agent_image,
            agent_name,
            network_name,
            config_path,
            state_dir,
            host_log_root,
            host_etc_root,
            args.timeout,
        )
        sources = _json_get(f"{server_url}/api/log-sources?website_id=website_smoke")["sources"]
        topology_hints = _json_get(f"{server_url}/api/topology-hints?website_id=website_smoke")["hints"]

        if args.ingest_mode == "evidence":
            with error_log.open("a", encoding="utf-8") as handle:
                handle.write("2026-07-17T00:00:30Z nginx worker ready\n")
            _run_agent_once(
                runtime,
                agent_image,
                agent_name,
                network_name,
                config_path,
                state_dir,
                host_log_root,
                host_etc_root,
                args.timeout,
            )

        with error_log.open("a", encoding="utf-8") as handle:
            handle.write("2026-07-17T00:01:00Z critical error disk full on /var/www\n")

        _run_agent_once(
            runtime,
            agent_image,
            agent_name,
            network_name,
            config_path,
            state_dir,
            host_log_root,
            host_etc_root,
            args.timeout,
        )

        agents = _json_get(f"{server_url}/api/agents")["agents"]
        events = _json_get(f"{server_url}/api/events/recent")["events"]
        incidents = _json_get(f"{server_url}/api/incidents")["incidents"]
        system_health = _json_get(f"{server_url}/api/system/health")

        _assert_smoke_results(sources, topology_hints, agents, events, incidents, system_health)
        _assert_gateway_routes(server_url, args.ingest_mode)
        summary.update(
            {
                "server_url": server_url,
                "agents": len(agents),
                "sources": len(sources),
                "topology_hints": len(topology_hints),
                "events": len(events),
                "incidents": len(incidents),
                "health_status": system_health["status"],
            }
        )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        print("AI Log Monitor container smoke passed")
        return 0
    finally:
        if not args.keep:
            _cleanup(runtime, [agent_name, gateway_name, server_name], network_name, [server_image, gateway_image, agent_image], temp_root)
        else:
            print(f"kept smoke resources under {temp_root}")


def _detect_runtime(requested: str) -> str:
    if requested != "auto":
        if shutil.which(requested):
            return requested
        raise SystemExit(f"{requested} was requested but is not on PATH")
    for candidate in ("podman", "docker"):
        if shutil.which(candidate):
            return candidate
    raise SystemExit("docker or podman is required for container smoke")


def _prepare_podman_runtime(runtime: str) -> None:
    if runtime != "podman" or os.name == "nt":
        return
    if not hasattr(os, "getuid"):
        return

    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if not runtime_dir:
        runtime_dir = f"/run/user/{os.getuid()}"
        os.environ["XDG_RUNTIME_DIR"] = runtime_dir

    runtime_path = Path(runtime_dir)
    try:
        (runtime_path / "containers" / "networks" / "aardvark-dns").mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise RuntimeError(
            f"Podman rootless runtime directory is not writable: {runtime_path}. "
            "Start a user session or set XDG_RUNTIME_DIR before running the smoke test."
        ) from exc


def _run(args: list[str], timeout: int) -> subprocess.CompletedProcess[str]:
    if args and args[0] == "podman":
        _prepare_podman_runtime("podman")
    result = subprocess.run(args, text=True, capture_output=True, timeout=timeout)
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed: {' '.join(args)}\nstdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _run_agent_once(
    runtime: str,
    agent_image: str,
    agent_name: str,
    network_name: str,
    config_path: Path,
    state_dir: Path,
    host_log_root: Path,
    host_etc_root: Path,
    timeout: int,
) -> None:
    agent_args = [
            runtime,
            "run",
            "--rm",
            "--name",
            agent_name,
            "-e",
            "ENROLL_TOKEN=install-token",
            "-v",
            _volume(config_path, "/etc/ai-log-agent/agent.yaml", runtime, readonly=True),
            "-v",
            _volume(state_dir, "/state", runtime),
            "-v",
            _volume(host_log_root, "/host/var/log", runtime, readonly=True),
            "-v",
            _volume(host_etc_root, "/host/etc", runtime, readonly=True),
            agent_image,
            "/app/ai-log-agent",
            "--config",
            "/etc/ai-log-agent/agent.yaml",
            "--once",
    ]
    if network_name:
        agent_args[5:5] = ["--network", network_name]
    _run(agent_args, timeout)


def _agent_server_url(runtime: str, gateway_name: str, published_port: int) -> str:
    del runtime, published_port
    return f"http://{gateway_name}:8888"


def _published_port(runtime: str, published_port: int) -> str:
    if runtime == "podman":
        return f"{published_port}:8888"
    return f"127.0.0.1:{published_port}:8888"


def _assert_smoke_results(
    sources: list[dict[str, Any]],
    topology_hints: list[dict[str, Any]],
    agents: list[dict[str, Any]],
    events: list[dict[str, Any]],
    incidents: list[dict[str, Any]],
    system_health: dict[str, Any],
) -> None:
    agent_by_id = {str(agent["agent_id"]): agent for agent in agents}
    if "web-smoke" not in agent_by_id:
        raise AssertionError(f"missing web-smoke agent: {agents}")
    if agent_by_id["web-smoke"].get("health_status") != "active":
        raise AssertionError(f"agent health_status was not active: {agent_by_id['web-smoke']}")
    if not any(_normalized_path(str(source["path"])).endswith("nginx/error.log") for source in sources):
        raise AssertionError(f"nginx/error.log source was not registered: {sources}")
    if not any(str(hint.get("target")) == "app-smoke:8080" for hint in topology_hints):
        raise AssertionError(f"app-smoke:8080 topology hint was not registered: {topology_hints}")
    if not any("critical error disk full" in str(event.get("message")) for event in events):
        raise AssertionError(f"critical error disk full event was not ingested: {events}")
    if not any(incident.get("website_id") == "website_smoke" for incident in incidents):
        raise AssertionError(f"website_smoke incident was not created: {incidents}")
    if int(system_health["checks"]["agents"]["total"]) != 1:
        raise AssertionError(f"system health did not see one agent: {system_health}")


def _assert_gateway_routes(server_url: str, ingest_mode: str) -> None:
    health = _json_get(f"{server_url}/health")
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise AssertionError(f"gateway /health did not return ok: {health}")
    if health.get("python") != "ok":
        raise AssertionError(f"gateway reports python not ok: {health}")
    runtime_stats = health.get(ingest_mode)
    if not isinstance(runtime_stats, dict):
        raise AssertionError(f"gateway health did not expose {ingest_mode} metrics: {health}")
    if ingest_mode == "shadow":
        if int(runtime_stats.get("inspected", 0)) < 1 or int(runtime_stats.get("matched", 0)) < 1:
            raise AssertionError(f"gateway shadow classifier did not inspect and match ingest: {runtime_stats}")
        if int(runtime_stats.get("mismatched", 0)) != 0:
            raise AssertionError(f"gateway shadow classifier disagreed with Python: {runtime_stats}")
    else:
        ingest = runtime_stats.get("ingest")
        context = runtime_stats.get("context")
        if not isinstance(ingest, dict) or int(ingest.get("buffered", 0)) < 1 or int(ingest.get("forwarded", 0)) < 1:
            raise AssertionError(f"gateway evidence mode did not buffer and forward: {runtime_stats}")
        if not isinstance(context, dict) or int(context.get("events", 0)) < 1:
            raise AssertionError(f"gateway evidence context is missing: {runtime_stats}")
    login_resp = _http_get(f"{server_url}/login")
    if login_resp.status != 200:
        raise AssertionError(f"/login returned {login_resp.status}, want 200")
    if "/login" not in login_resp.body.decode("utf-8", errors="replace"):
        raise AssertionError(f"/login body does not contain /login path")
    static_resp = _http_get(f"{server_url}/static/css/styles.css")
    if static_resp.status != 200:
        raise AssertionError(f"/static/css/styles.css returned {static_resp.status}, want 200")
    if "text/css" not in static_resp.headers.get("Content-Type", ""):
        raise AssertionError(f"static CSS Content-Type is not text/css")


def _wait_for_health(server_url: str, timeout: int) -> None:
    deadline = time.time() + timeout
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            resp = _json_get(f"{server_url}/health")
            if isinstance(resp, dict) and resp.get("status") == "ok":
                return
        except Exception as exc:  # noqa: BLE001
            last_error = exc
        time.sleep(0.5)
    raise TimeoutError(f"server did not become healthy: {last_error}")


def _json_get(url: str) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


class _HttpGetResult:
    status: int
    headers: dict[str, str]
    body: bytes

    def __init__(self, status: int, headers: dict[str, str], body: bytes) -> None:
        self.status = status
        self.headers = headers
        self.body = body


def _http_get(url: str) -> _HttpGetResult:
    with urllib.request.urlopen(url, timeout=10) as response:
        body = response.read()
        headers = {k: v for k, v in response.headers.items()}
        return _HttpGetResult(response.status, headers, body)


def _volume(host_path: Path, container_path: str, runtime: str, readonly: bool = False) -> str:
    suffix = ":ro" if readonly else ""
    if runtime == "podman" and os.name != "nt":
        suffix += ",Z" if readonly else ":Z"
    return f"{host_path.resolve()}{':' if os.name != 'nt' else ':'}{container_path}{suffix}"


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _cleanup(runtime: str, containers: list[str], network_name: str, images: list[str], temp_root: Path) -> None:
    for container in containers:
        subprocess.run([runtime, "rm", "-f", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if network_name:
        subprocess.run([runtime, "network", "rm", network_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for image in images:
        subprocess.run([runtime, "image", "rm", "-f", image], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    shutil.rmtree(temp_root, ignore_errors=True)


def _normalized_path(path: str) -> str:
    return path.replace("\\", "/")


if __name__ == "__main__":
    sys.exit(main())
