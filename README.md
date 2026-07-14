# AI Log Monitor

Podman-first MVP for a central LAN log monitor and incident analyzer.

## What Exists Now

- `POST /api/agents/register` with `X-Enroll-Token`
- Agent registration auto-creates and attaches the target website when `agent.website_id` is set
- `POST /api/ingest` to normalize, classify, and store events
- `POST /api/files/import` to upload a log file into a selected website bucket
- Automatic incident creation for `problem` and `critical` events
- `GET /api/analyze?website_id=website_1` website-isolated AI report with mock, Ollama, or API mode
- Incident memory for repeated patterns, stored per website
- `GET /` file-first dashboard for choosing `website_1`, `website_2`, or a custom website ID
- Optional username/password login for dashboard, backed by signed sessions
- Optional `ADMIN_TOKEN` for management API access
- Optional `ENFORCE_AGENT_TOKEN=true` to require agent tokens on `/api/ingest`
- Startup retention cleanup with `RETENTION_DAYS`
- SQLite storage in `/data/database.db`

## Run Locally

Recommended on this Windows machine:

```powershell
.\manage.ps1 Start
.\manage.ps1 Status
.\manage.ps1 Open
.\manage.ps1 Test
.\manage.ps1 Stop
```

`manage.ps1` automatically loads `server/secrets.env`, uses `data/` as the local database folder, and runs the web app on port `8888`.

Manual mode:

```powershell
$env:AI_LOG_DATA_DIR = "$PWD\data"
$env:ENROLL_TOKEN = "change-this-install-token"
$env:ADMIN_USER = "admin"
$env:ADMIN_PASSWORD = "change-me-now"
$env:ADMIN_TOKEN = "change-this-admin-token"
$env:ENFORCE_AGENT_TOKEN = "true"
$env:RETENTION_DAYS = "30"
python -m server.main
```

Open:

```text
http://127.0.0.1:8888/
```

The dashboard starts with `Import Log File`: choose the target website, pick a log file, then import. The server auto-creates that website bucket and analyzes only the imported lines for that website.
If `ADMIN_USER` and `ADMIN_PASSWORD` are set, login with that username and password before using the dashboard.

## Run With Podman

On the AI Server machine:

```bash
git clone <your-git-url> ai-log-monitor
cd ai-log-monitor
cp server/secrets.env.example server/secrets.env
```

Edit `server/secrets.env` and `server/ai.yaml` before real use.

```bash
podman compose up --build
```

## Run Linux Agent With Podman

On a Linux client machine, edit:

```text
agent/secrets.env
agent/agent.yaml
```

Create the secret file first:

```bash
cp agent/secrets.env.example agent/secrets.env
```

Then run:

```bash
podman compose -f agent/compose.yaml up --build
```

The agent mounts `/var/log` read-only, stores offsets in `agent/state`, and sends only matched problem lines by default.
Set `agent.website_id` in `agent/agent.yaml`; the AI Server will create that website bucket and attach the machine on first register.

## AI Modes

Edit `server/ai.yaml`.

- `mode: "mock"` keeps analysis local and rule-based.
- `mode: "ollama"` calls a local/LAN Ollama `/api/generate` endpoint.
- `mode: "api"` calls an OpenAI-compatible chat-completions endpoint using `AI_API_ENDPOINT`, `AI_API_KEY`, and `AI_API_MODEL`.

All modes still isolate context by `website_id`, and repeated patterns are saved in SQLite incident memory.

## Test

```powershell
python -m unittest discover -s tests -v
```

## Example Ingest

Register the agent first and keep the returned `agent_token`.

```bash
curl -X POST http://127.0.0.1:8888/api/agents/register \
  -H "Content-Type: application/json" \
  -H "X-Enroll-Token: change-this-install-token" \
  -d '{
    "website_id":"website_1",
    "agent_id":"web01",
    "agent_role":"web"
  }'
```

Then send log events with `X-Agent-Token` when `ENFORCE_AGENT_TOKEN=true`.

```bash
curl -X POST http://127.0.0.1:8888/api/ingest \
  -H "Content-Type: application/json" \
  -H "X-Agent-Token: agt_from_register_response" \
  -d '{
    "website_id":"website_1",
    "agent_id":"web01",
    "agent_role":"web",
    "timestamp":"2026-07-14T10:32:11+07:00",
    "status_code":502,
    "message":"upstream timed out while reading response header from upstream"
  }'
```
