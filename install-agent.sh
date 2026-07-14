#!/usr/bin/env bash
set -euo pipefail

SERVER_URL=""
ENROLL_TOKEN=""
AGENT_NAME="$(hostname)"
AGENT_ROLE="unknown"
WEBSITE_ID=""
START_AGENT="true"

usage() {
  cat <<'EOF'
AI Log Monitor - Agent installer

Usage:
  ./install-agent.sh \
    --server-url http://10.1.15.180:8888 \
    --enroll-token YOUR_ENROLL_TOKEN \
    --name db1 \
    --role db \
    --website-id website_1

Options:
  --server-url     AI Server URL reachable from this client.
  --enroll-token   Token from server/secrets.env ENROLL_TOKEN.
  --name           Friendly machine name. Default: hostname.
  --role           Machine role: web, db, app, lb, cache. Default: unknown.
  --website-id     Website/group boundary, for example website_1.
  --no-start       Write config only; do not start the agent.
  -h, --help       Show this help.
EOF
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --server-url)
      SERVER_URL="${2:-}"
      shift 2
      ;;
    --enroll-token)
      ENROLL_TOKEN="${2:-}"
      shift 2
      ;;
    --name)
      AGENT_NAME="${2:-}"
      shift 2
      ;;
    --role)
      AGENT_ROLE="${2:-}"
      shift 2
      ;;
    --website-id)
      WEBSITE_ID="${2:-}"
      shift 2
      ;;
    --no-start)
      START_AGENT="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [ -z "$SERVER_URL" ] || [ -z "$ENROLL_TOKEN" ] || [ -z "$WEBSITE_ID" ]; then
  echo "Missing required values: --server-url, --enroll-token, and --website-id are required." >&2
  usage >&2
  exit 2
fi

validate_enroll_token() {
  case "$ENROLL_TOKEN" in
    *YOUR_ENROLL_TOKEN*|*change-this-install-token*|*ใส่*|*ของ_server*)
      echo "ENROLL_TOKEN must be the real ASCII token from server/secrets.env, not the example placeholder." >&2
      exit 2
      ;;
  esac

  if ! LC_ALL=C printf '%s' "$ENROLL_TOKEN" | grep -Eq '^[!-~]+$'; then
    echo "ENROLL_TOKEN must be the real ASCII token from server/secrets.env, not Thai text or spaces." >&2
    exit 2
  fi
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

SUDO=""
if [ "$(id -u)" -ne 0 ]; then
  SUDO="sudo"
fi

install_runtime_if_needed() {
  if command -v podman >/dev/null 2>&1 && command -v podman-compose >/dev/null 2>&1; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update
    $SUDO apt-get install -y podman podman-compose
    return
  fi

  echo "podman or podman-compose is missing. Install them first, then rerun this script." >&2
  exit 1
}

write_agent_files() {
  mkdir -p agent/state
  umask 077
  printf 'ENROLL_TOKEN=%s\n' "$ENROLL_TOKEN" > agent/secrets.env
  chmod 600 agent/secrets.env

  AI_LOG_SERVER_URL="$SERVER_URL" \
  AI_LOG_AGENT_NAME="$AGENT_NAME" \
  AI_LOG_AGENT_ROLE="$AGENT_ROLE" \
  AI_LOG_WEBSITE_ID="$WEBSITE_ID" \
  python3 - <<'PY'
import os
from pathlib import Path

path = Path("agent/agent.yaml")
text = path.read_text(encoding="utf-8")

replacements = {
    "url": os.environ["AI_LOG_SERVER_URL"],
    "name": os.environ["AI_LOG_AGENT_NAME"],
    "role": os.environ["AI_LOG_AGENT_ROLE"],
    "website_id": os.environ["AI_LOG_WEBSITE_ID"],
}

def replace_in_section(source: str, section: str, key: str, value: str) -> str:
    lines = source.splitlines()
    in_section = False
    for index, line in enumerate(lines):
        if line and not line.startswith(" ") and line.endswith(":"):
            in_section = line[:-1] == section
            continue
        if in_section and line.startswith(f"  {key}:"):
            lines[index] = f'  {key}: "{value}"'
            return "\n".join(lines) + "\n"
    raise SystemExit(f"Could not find {section}.{key} in agent/agent.yaml")

text = replace_in_section(text, "server", "url", replacements["url"])
text = replace_in_section(text, "agent", "name", replacements["name"])
text = replace_in_section(text, "agent", "role", replacements["role"])
text = replace_in_section(text, "agent", "website_id", replacements["website_id"])
path.write_text(text, encoding="utf-8")
PY
}

start_agent() {
  if [ -n "$SUDO" ]; then
    podman rm -f ai-log-agent >/dev/null 2>&1 || true
  fi
  $SUDO podman rm -f ai-log-agent >/dev/null 2>&1 || true
  $SUDO podman compose -f agent/compose.yaml up -d --build
  $SUDO podman logs --tail 40 ai-log-agent || true
}

validate_enroll_token
install_runtime_if_needed
write_agent_files

if [ "$START_AGENT" = "true" ]; then
  start_agent
fi

echo "AI Log Monitor agent configured:"
echo "  server: $SERVER_URL"
echo "  agent:  $AGENT_NAME ($AGENT_ROLE)"
echo "  group:  $WEBSITE_ID"
