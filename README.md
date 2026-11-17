# AI Log Monitor

Self-hosted LAN log monitor for one admin user, multiple websites, and Linux agents.

The product has two installable parts:

- `server/`: central dashboard and API.
- `agent/`: Linux machine log collector.

The normal dashboard flow is:

```text
Websites -> Website -> Machines -> Logs
```

Each website is isolated by `website_id`. Agents only need the server URL, enroll token,
website ID, machine name, and role.

## Code Layout

```text
agent/
  main.go              startup loop
  config.go            configuration loading
  discovery.go         log and topology discovery
  scanner.go           incremental log reading and filtering
  spool.go             offline event queue
  transport.go         registration, heartbeat, and ingest API
  *_test.go             tests grouped by the same responsibilities

server/server/app/
  app.py               application facade and route dispatch
  app_auth.py           login and session security
  app_health.py         system and agent health checks
  app_handlers.py       ingest and management request handlers
  analysis.py          root-cause analysis orchestration
  ai_settings.py       AI configuration persistence
  notifications.py     alert delivery
  storage.py           SQLite connection and schema facade
  storage_registry.py  websites, agents, sources, and topology
  storage_events.py    events, incidents, and incident memory
  ui.py                dashboard shell and page routing
  ui_pages.py           primary dashboard pages
  ui_panels.py          reusable operational panels
  ui_helpers.py         links, badges, pagination, and formatting

test/
  server/               server tests
  agent/                installer and configuration tests
```

## Server Install

Run on the central Linux server:

```bash
./server/install-server.sh \
  --public-url http://10.1.0.10:8888 \
  --admin-user admin \
  --admin-password CHANGE_ME \
  --enroll-token CHANGE_ME
```

Optional notification webhooks:

```bash
./server/install-server.sh \
  --public-url http://10.1.0.10:8888 \
  --admin-user admin \
  --admin-password CHANGE_ME \
  --enroll-token CHANGE_ME \
  --line-webhook-url "$LINE_WEBHOOK_URL" \
  --google-chat-webhook-url "$GOOGLE_CHAT_WEBHOOK_URL"
```

Use `--dry-run` first to check the plan without writing files. Do not put real tokens in chat.

## Server Control

Linux:

```bash
systemctl status ai-log-monitor-server.service
systemctl restart ai-log-monitor-server.service
./server/manage.sh doctor
./server/manage.sh status
./server/manage.sh backup
./server/manage.sh update
```

Windows local development:

Script path: `server/manage.ps1`

```powershell
.\server\manage.ps1 -Action Doctor
.\server\manage.ps1 -Action Status
.\server\manage.ps1 -Action Backup
```

## Agent Install

Run on each Linux machine that belongs to a website:

```bash
./agent/install-agent.sh \
  --server-url http://10.1.0.10:8888 \
  --enroll-token CHANGE_ME \
  --website-id website_1 \
  --name web01 \
  --role web
```

Use `--dry-run` first to validate the command without writing `secrets.env` or changing
`agent.yaml`.

Use the agent doctor on a Linux machine to check container runtime, config files,
state directory, host log access, systemd, and server health without printing secrets:

```bash
./agent/install-agent.sh --doctor --server-url http://10.1.0.10:8888
```

The installer enables a systemd unit when systemd is available:

```bash
systemctl status ai-log-monitor-agent.service
systemctl restart ai-log-monitor-agent.service
```

The default agent container mounts these host paths read-only:

- `/var/log` -> `/host/var/log`
- `/etc` -> `/host/etc`
- `/opt` -> `/host/opt`
- `/srv` -> `/host/srv`

The agent auto-discovers readable Linux logs under those roots and reports the discovered
sources to the server before sending matched log events.
It also inspects safe, bounded config files such as nginx proxy rules and app database
host settings to send website-scoped topology hints for AI analysis.

After first registration, the agent stores its private `agent_token` in `agent/state`
and reuses it on restart. If the server rejects that token, the agent re-registers with
the enroll token and saves the refreshed token.

## Gateway

The Go gateway (port `:8888`) proxies requests to the internal Python server (port `:8889`). The gateway operates in **shadow mode**: every `POST /api/ingest` is classified locally while the request is forwarded to Python. Python remains authoritative — its response is always returned to the client.

Set `GATEWAY_INGEST_MODE=evidence` only after shadow metrics show no mismatches. In evidence mode, the Gateway validates Agent tokens through a five-minute cache, keeps normal lines in bounded RAM, and forwards only warning/problem/critical evidence to Python. Set the mode back to `shadow` and restart the Gateway for an immediate rollback. `GATEWAY_INTERNAL_TOKEN` must match in the Gateway and Python containers.

## AI And Alerts

The default behavior is:

- Critical logs are analyzed immediately.
- Analysis uses a 30 minute website-scoped context window.
- Incident memory is stored per website, never shared across websites.
- Incident memory is not deleted by event retention, so repeated problems stay recognizable after raw log events expire.
- Alerts can be sent to LINE and Google Chat when webhook URLs are configured.

Dashboard settings can change analysis window, minimum auto-analysis severity, language,
AI mode/provider/model, and notification webhooks.

## Local Verification

From this repository:

```powershell
cd C:\ai_server_log\server
python -m unittest discover -s ../test/server -v

cd C:\ai_server_log\agent
go test -v ./...
go vet ./...
python -m unittest discover -s ../test/agent -v
```

Container release smoke test:

```powershell
python scripts/container_smoke.py --runtime docker
```

On a Linux host with Podman:

```bash
python3 scripts/container_smoke.py --runtime podman
```

The smoke test builds the server and agent images, starts a temporary server,
runs the agent twice against a temporary `nginx/error.log`, and verifies agent
registration, log-source discovery, event ingest, incident creation, and health
status before cleaning up.

The server health endpoint is:

```text
http://127.0.0.1:8888/health
```

The richer system diagnostics endpoint is:

```text
http://127.0.0.1:8888/api/system/health
```

It reports database status, writable data directory status, open incidents, and stale
agents that have stopped sending heartbeats.

The `GET /api/agents` response keeps `status` as the last status reported by the
agent and adds `health_status` (`active` or `stale`) based on heartbeat age so the
dashboard can show machines that have gone quiet.
