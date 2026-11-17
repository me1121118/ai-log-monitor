#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$ROOT/data"
BACKUP_DIR="$ROOT/backups"
CONFIG_DIR="$ROOT/server"
COMPOSE_FILE="$ROOT/compose.yaml"
PORT="${AI_LOG_PORT:-8888}"
LOCAL_URL="http://127.0.0.1:${PORT}/"
HEALTH_URL="http://127.0.0.1:${PORT}/health"

usage() {
  echo "Usage: ./manage.sh {start|stop|restart|status|test|backup|restore|update|open|clean|doctor} [backup.zip]"
}

compose_cmd() {
  if command -v podman >/dev/null 2>&1 && podman compose version >/dev/null 2>&1; then
    echo "podman compose"
    return 0
  fi
  if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return 0
  fi
  echo "podman compose or docker compose is required" >&2
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
  echo "python3 or python is required" >&2
  return 1
}

load_env() {
  mkdir -p "$DATA_DIR" "$BACKUP_DIR"
  export AI_LOG_DATA_DIR="${AI_LOG_DATA_DIR:-/data}"
  export AI_LOG_HOST="${AI_LOG_HOST:-0.0.0.0}"
  export AI_LOG_PORT="$PORT"
}

wait_for_health() {
  for _ in $(seq 1 40); do
    if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
      return 0
    fi
    sleep 0.25
  done
  return 1
}

start_server() {
  load_env
  local compose
  compose="$(compose_cmd)"
  (cd "$ROOT" && $compose -f "$COMPOSE_FILE" up -d --build)
  wait_for_health
  echo "AI Log Monitor started on $LOCAL_URL"
}

stop_server() {
  local compose
  compose="$(compose_cmd)"
  (cd "$ROOT" && $compose -f "$COMPOSE_FILE" down)
  echo "AI Log Monitor stopped."
}

status_server() {
  local compose
  compose="$(compose_cmd)"
  (cd "$ROOT" && $compose -f "$COMPOSE_FILE" ps)
  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "health: ok"
  else
    echo "health: not healthy"
  fi
}

test_project() {
  local PYTHON
  PYTHON="$(python_cmd)"
  (cd "$ROOT" && "$PYTHON" -m unittest discover -s ../test/server -v)
}

backup_server() {
  load_env
  local PYTHON
  PYTHON="$(python_cmd)"
  (cd "$ROOT" && "$PYTHON" -m server.app.maintenance backup \
    --data-dir "$DATA_DIR" \
    --backup-dir "$BACKUP_DIR" \
    --config "$CONFIG_DIR/ai.yaml" \
    --config "$CONFIG_DIR/config.yaml")
}

restore_server() {
  local archive="${1:-}"
  if [[ -z "$archive" ]]; then
    echo "restore requires a backup zip path" >&2
    exit 1
  fi
  local PYTHON
  PYTHON="$(python_cmd)"
  (cd "$ROOT" && "$PYTHON" -m server.app.maintenance restore \
    --archive "$archive" \
    --data-dir "$DATA_DIR" \
    --config-dir "$CONFIG_DIR")
}

update_server() {
  backup_server
  local compose
  compose="$(compose_cmd)"
  (cd "$ROOT" && $compose -f "$COMPOSE_FILE" build)
  (cd "$ROOT" && $compose -f "$COMPOSE_FILE" up -d)
  wait_for_health
  echo "AI Log Monitor update completed after backup."
}

open_dashboard() {
  echo "$LOCAL_URL"
}

clean_cache() {
  find "$ROOT" -type d -name __pycache__ -prune -exec rm -rf {} +
}

doctor_server() {
  local failed=0
  echo "AI Log Monitor server doctor"

  local compose
  if compose="$(compose_cmd)"; then
    echo "container runtime: ok ($compose)"
  else
    echo "container runtime: missing podman compose or docker compose"
    failed=1
  fi

  local PYTHON
  if PYTHON="$(python_cmd)"; then
    echo "python: ok ($PYTHON)"
  else
    echo "python: missing"
    failed=1
  fi

  if [[ -f "$COMPOSE_FILE" ]]; then
    echo "compose file: ok ($COMPOSE_FILE)"
  else
    echo "compose file: missing ($COMPOSE_FILE)"
    failed=1
  fi

  if [[ -f "$CONFIG_DIR/secrets.env" ]]; then
    echo "secrets: ok ($CONFIG_DIR/secrets.env)"
  else
    echo "secrets: missing ($CONFIG_DIR/secrets.env)"
    failed=1
  fi

  mkdir -p "$DATA_DIR"
  if printf 'ok\n' > "$DATA_DIR/.doctor.tmp" 2>/dev/null; then
    rm -f "$DATA_DIR/.doctor.tmp"
    echo "data dir writable: ok ($DATA_DIR)"
  else
    echo "data dir writable: failed ($DATA_DIR)"
    failed=1
  fi

  if command -v systemctl >/dev/null 2>&1 && systemctl list-units >/dev/null 2>&1; then
    echo "systemd: available"
  else
    echo "systemd: not available or not running"
  fi

  if curl -fsS "$HEALTH_URL" >/dev/null 2>&1; then
    echo "server health: ok ($HEALTH_URL)"
  else
    echo "server health: not running or not healthy ($HEALTH_URL)"
  fi

  return "$failed"
}

ACTION="${1:-status}"
case "$ACTION" in
  start) start_server ;;
  stop) stop_server ;;
  restart) stop_server; start_server ;;
  status) status_server ;;
  test) test_project ;;
  backup) backup_server ;;
  restore) restore_server "${2:-}" ;;
  update) update_server ;;
  open) open_dashboard ;;
  clean) clean_cache ;;
  doctor) doctor_server ;;
  -h|--help|help) usage ;;
  *) usage; exit 1 ;;
esac
