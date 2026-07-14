from __future__ import annotations

import argparse
import socket
import time

from .client import AgentClient
from .config import AgentConfig, load_agent_config
from .discovery import with_discovered_log_paths
from .scanner import scan_once


def main() -> None:
    parser = argparse.ArgumentParser(description="AI Log Monitor Linux Agent")
    parser.add_argument("--config", default="/etc/ai-log-agent/agent.yaml")
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    config = with_discovered_log_paths(load_agent_config(args.config))
    client = AgentClient(config.server_url)
    agent_token = _register(config, client)

    while True:
        events = scan_once(config)
        for event in events:
            client.ingest(agent_token, event)
        if args.once:
            break
        time.sleep(config.heartbeat_interval_seconds)


def _register(config: AgentConfig, client: AgentClient) -> str:
    payload = {
        "agent_id": config.agent_id,
        "agent_role": config.agent_role,
        "hostname": socket.gethostname(),
    }
    if config.website_id:
        payload["website_id"] = config.website_id

    result = client.register(
        config.enroll_token,
        payload,
    )
    return str(result["agent_token"])


if __name__ == "__main__":
    main()
