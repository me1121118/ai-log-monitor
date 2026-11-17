#!/usr/bin/env bash
set -euo pipefail

SERVER_URL=""
ENROLL_TOKEN=""
AGENT_NAME="$(hostname)"
AGENT_ROLE="unknown"
WEBSITE_ID=""
START_AGENT="true"
DRY_RUN="false"
DOCTOR="false"
USE_SYSTEMD="true"
SERVICE_NAME="ai-log-monitor-agent.service"
SERVICE_FILE="/etc/systemd/system/$SERVICE_NAME"

usage() {
  cat <<'EOF'
AI Log Monitor - Agent installer

Usage:
  ./install-agent.sh \
    --server-url http://10.1.0.10:8888 \
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
  --no-systemd     Do not install or enable a systemd service.
  --dry-run        Validate options and show the install plan without writing files.
  --doctor         Check runtime, config files, systemd, host logs, and server health.
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
    --no-systemd)
      USE_SYSTEMD="false"
      shift
      ;;
    --dry-run)
      DRY_RUN="true"
      shift
      ;;
    --doctor)
      DOCTOR="true"
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

COMPOSE_KIND=""
COMPOSE_BIN=""

detect_compose() {
  local bin
  if bin="$(command -v podman 2>/dev/null)" && "$bin" compose version >/dev/null 2>&1; then
    COMPOSE_KIND="podman-plugin"
    COMPOSE_BIN="$bin"
    return 0
  fi
  if bin="$(command -v podman-compose 2>/dev/null)"; then
    COMPOSE_KIND="podman-compose"
    COMPOSE_BIN="$bin"
    return 0
  fi
  if bin="$(command -v docker 2>/dev/null)" && "$bin" compose version >/dev/null 2>&1; then
    COMPOSE_KIND="docker-plugin"
    COMPOSE_BIN="$bin"
    return 0
  fi
  return 1
}

python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return 0
  fi
  echo "python3 or python is required to write agent.yaml." >&2
  exit 1
}

install_runtime_if_needed() {
  if detect_compose; then
    return
  fi

  if command -v apt-get >/dev/null 2>&1; then
    $SUDO apt-get update
    $SUDO apt-get install -y podman podman-compose
    detect_compose && return
  fi

  echo "podman compose, podman-compose, or docker compose is missing. Install one, then rerun this script." >&2
  exit 1
}

write_agent_files() {
  local py
  py="$(python_cmd)"

  mkdir -p state
  umask 077
  printf 'ENROLL_TOKEN=%s\n' "$ENROLL_TOKEN" > secrets.env
  chmod 600 secrets.env

  AI_LOG_SERVER_URL="$SERVER_URL" \
  AI_LOG_AGENT_NAME="$AGENT_NAME" \
  AI_LOG_AGENT_ROLE="$AGENT_ROLE" \
  AI_LOG_WEBSITE_ID="$WEBSITE_ID" \
  "$py" - <<'PY'
import os
from pathlib import Path

path = Path("agent.yaml")
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
    raise SystemExit(f"Could not find {section}.{key} in agent.yaml")

text = replace_in_section(text, "server", "url", replacements["url"])
text = replace_in_section(text, "agent", "name", replacements["name"])
text = replace_in_section(text, "agent", "role", replacements["role"])
text = replace_in_section(text, "agent", "website_id", replacements["website_id"])
path.write_text(text, encoding="utf-8")
PY
}

compose_up() {
  case "$COMPOSE_KIND" in
    podman-plugin)
      $SUDO "$COMPOSE_BIN" compose -f compose.yaml up -d --build
      ;;
    podman-compose)
      $SUDO "$COMPOSE_BIN" -f compose.yaml up -d --build
      ;;
    docker-plugin)
      $SUDO "$COMPOSE_BIN" compose -f compose.yaml up -d --build
      ;;
    *)
      echo "Container runtime was not detected." >&2
      exit 1
      ;;
  esac
}

show_agent_logs() {
  case "$COMPOSE_KIND" in
    podman-plugin|podman-compose)
      $SUDO podman logs --tail 40 ai-log-agent || true
      ;;
    docker-plugin)
      $SUDO docker logs --tail 40 ai-log-agent || true
      ;;
  esac
}

start_agent() {
  case "$COMPOSE_KIND" in
    podman-plugin|podman-compose)
      $SUDO podman rm -f ai-log-agent >/dev/null 2>&1 || true
      ;;
    docker-plugin)
      $SUDO docker rm -f ai-log-agent >/dev/null 2>&1 || true
      ;;
  esac
  compose_up
  show_agent_logs
}

systemd_available() {
  command -v systemctl >/dev/null 2>&1 && systemctl list-units >/dev/null 2>&1
}

compose_start_command() {
  case "$COMPOSE_KIND" in
    podman-plugin|docker-plugin)
      echo "$COMPOSE_BIN compose -f compose.yaml up -d --build"
      ;;
    podman-compose)
      echo "$COMPOSE_BIN -f compose.yaml up -d --build"
      ;;
    *)
      return 1
      ;;
  esac
}

compose_stop_command() {
  case "$COMPOSE_KIND" in
    podman-plugin|docker-plugin)
      echo "$COMPOSE_BIN compose -f compose.yaml down"
      ;;
    podman-compose)
      echo "$COMPOSE_BIN -f compose.yaml down"
      ;;
    *)
      return 1
      ;;
  esac
}

write_systemd_service() {
  if [ "$USE_SYSTEMD" != "true" ]; then
    return 0
  fi
  if ! systemd_available; then
    echo "systemd not found; skipping service install"
    return 1
  fi

  local start_cmd
  local stop_cmd
  start_cmd="$(compose_start_command)"
  stop_cmd="$(compose_stop_command)"

  $SUDO tee "$SERVICE_FILE" >/dev/null <<EOF
[Unit]
Description=AI Log Monitor Agent
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$SCRIPT_DIR
ExecStart=$start_cmd
ExecStop=$stop_cmd
RemainAfterExit=yes
TimeoutStartSec=180

[Install]
WantedBy=multi-user.target
EOF
  $SUDO systemctl daemon-reload
  $SUDO systemctl enable ai-log-monitor-agent.service
  return 0
}

start_or_enable_agent() {
  if [ "$USE_SYSTEMD" = "true" ] && systemd_available; then
    write_systemd_service
    if [ "$START_AGENT" != "true" ]; then
      echo "Agent files written. Start later with: sudo systemctl start $SERVICE_NAME"
      return 0
    fi
    $SUDO systemctl restart "$SERVICE_NAME"
    show_agent_logs
    return 0
  fi

  if [ "$START_AGENT" = "true" ]; then
    start_agent
  fi
}

doctor_agent() {
  local failed=0
  echo "AI Log Monitor agent doctor"

  if detect_compose; then
    echo "container runtime: ok ($COMPOSE_KIND)"
  else
    echo "container runtime: missing podman compose, podman-compose, or docker compose"
    failed=1
  fi

  if python_cmd >/dev/null; then
    echo "python: ok"
  else
    echo "python: missing"
    failed=1
  fi

  if [ -f "agent.yaml" ]; then
    echo "agent config: ok ($SCRIPT_DIR/agent.yaml)"
  else
    echo "agent config: missing ($SCRIPT_DIR/agent.yaml)"
    failed=1
  fi

  if [ -f "compose.yaml" ]; then
    echo "compose file: ok ($SCRIPT_DIR/compose.yaml)"
  else
    echo "compose file: missing ($SCRIPT_DIR/compose.yaml)"
    failed=1
  fi

  if [ -f "secrets.env" ]; then
    echo "secrets: ok ($SCRIPT_DIR/secrets.env)"
  else
    echo "secrets: missing ($SCRIPT_DIR/secrets.env)"
  fi

  mkdir -p state
  if printf 'ok\n' > state/.doctor.tmp 2>/dev/null; then
    rm -f state/.doctor.tmp
    echo "state dir writable: ok ($SCRIPT_DIR/state)"
  else
    echo "state dir writable: failed ($SCRIPT_DIR/state)"
    failed=1
  fi

  if [ -r /var/log ]; then
    echo "host logs: ok (/var/log readable)"
  else
    echo "host logs: not readable (/var/log)"
  fi

  if systemd_available; then
    echo "systemd: available"
  else
    echo "systemd: not available or not running"
  fi

  if [ -n "$SERVER_URL" ]; then
    if command -v curl >/dev/null 2>&1 && curl -fsS "${SERVER_URL%/}/health" >/dev/null 2>&1; then
      echo "server health: ok (${SERVER_URL%/}/health)"
    else
      echo "server health: failed (${SERVER_URL%/}/health)"
      failed=1
    fi
  else
    echo "server health: skipped (pass --server-url to check)"
  fi

  return "$failed"
}

if [ "$DOCTOR" = "true" ]; then
  doctor_agent
  exit $?
fi

if [ -z "$SERVER_URL" ] || [ -z "$ENROLL_TOKEN" ] || [ -z "$WEBSITE_ID" ]; then
  echo "Missing required values: --server-url, --enroll-token, and --website-id are required." >&2
  usage >&2
  exit 2
fi

validate_enroll_token

if [ "$DRY_RUN" = "true" ]; then
  echo "DRY RUN"
  echo "AI Log Monitor agent install plan"
  echo "server: $SERVER_URL"
  echo "agent:  $AGENT_NAME ($AGENT_ROLE)"
  echo "group:  $WEBSITE_ID"
  echo "enroll token: configured"
  echo "runtime: not checked in dry run; use --doctor for runtime checks"
  if [ "$USE_SYSTEMD" = "true" ]; then
    echo "systemd: enabled"
  else
    echo "systemd: disabled"
  fi
  echo "start: $START_AGENT"
  exit 0
fi

install_runtime_if_needed
write_agent_files
start_or_enable_agent

echo "AI Log Monitor agent configured:"
echo "  server: $SERVER_URL"
echo "  agent:  $AGENT_NAME ($AGENT_ROLE)"
echo "  group:  $WEBSITE_ID"
