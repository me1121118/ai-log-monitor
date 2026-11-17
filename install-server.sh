#!/usr/bin/env bash
set -euo pipefail

# Simple 1-step installer for AI Log Monitor Server (Podman / Docker)
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR/server"

if [ ! -f .env ] && [ -f .env.example ]; then
  cp .env.example .env
  echo "[install-server] Created server/.env from .env.example (please review tokens/passwords)."
fi

if command -v podman >/dev/null 2>&1; then
  if podman compose version >/dev/null 2>&1; then
    podman compose up -d --build
  elif command -v podman-compose >/dev/null 2>&1; then
    podman-compose up -d --build
  else
    echo "[install-server] Podman found. Starting container..."
    podman build -t ai-log-server -f server/Containerfile .
    podman rm -f ai-log-server >/dev/null 2>&1 || true
    podman run -d --name ai-log-server -p 8888:8888 -v "$ROOT_DIR/data:/data" ai-log-server
  fi
elif command -v docker >/dev/null 2>&1; then
  docker compose up -d --build
else
  echo "[install-server] Error: Please install docker or podman first."
  exit 1
fi

echo "[install-server] AI Log Monitor Server is running on port 8888!"
