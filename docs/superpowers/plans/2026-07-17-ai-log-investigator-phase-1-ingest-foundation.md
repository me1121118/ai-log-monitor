# AI Log Investigator Phase 1 Ingest Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the first production foundation slice for relevance-based log source discovery, source registration, event metadata, timestamp normalization, and agent buffering hooks.

**Architecture:** Keep the existing Python server and Go agent, adding focused interfaces instead of replacing the app. The server remains SQLite-backed in this phase so current tests and local workflow stay stable; the schema is shaped so a PostgreSQL backend can be introduced in a later storage phase. The Go agent starts emitting source metadata and stable event IDs, while deeper service scanners and dashboard topology are later phases.

**Tech Stack:** Python stdlib `unittest` and `sqlite3`, existing Python server modules under `C:\ai_server_log\server\server\app`, Go agent under `C:\ai_server_log\agent`, Go tests with `go test`.

## Global Constraints

- Central server first target: Linux + Podman appliance, but local development currently runs on Windows.
- Agent first target: Linux privileged `systemd` service.
- `website_id` is the hard isolation key for logs, agents, sources, incidents, reports, topology, and memory.
- Agent config remains minimal: `server_url`, `website_id`, `agent_name`, and enrollment token.
- Agent discovery is relevance-based and must not be locked to a fixed program whitelist.
- Known services are classifiers and shortcuts, not the only supported sources.
- Raw log retention default remains 24 hours.
- AI provider remains OpenAI-compatible API in later phases; this phase must not block existing mock analysis.
- No remote shell or arbitrary remote command execution.
- No silent loss of important events; if loss happens later because a bounded buffer is full, it must be represented by a marker event.
- `C:\ai_server_log` is not currently a git repository, so commit steps are replaced with verification checkpoints.

---

## File Structure

- Modify `C:\ai_server_log\server\server\app\storage.py`
  - Add `log_sources` table.
  - Add `event_seen_ids` or equivalent dedupe behavior through existing `events.event_id`.
  - Add source registration and listing methods.
  - Preserve existing incident grouping behavior.
- Modify `C:\ai_server_log\server\server\app\core.py`
  - Add timestamp normalization helper.
  - Add metadata preservation for `source_id`, `source_confidence`, `timestamp_confidence`, `event_uid`, and multiline flags.
- Modify `C:\ai_server_log\server\server\app\app.py`
  - Add `POST /api/log-sources` for agent source registration.
  - Add `GET /api/log-sources?website_id=...&agent_id=...`.
  - Return dedupe-friendly ingest responses.
- Create or modify `C:\ai_server_log\server\tests\test_log_sources.py`
  - Cover source registration, website isolation, source metadata, and update behavior.
- Create or modify `C:\ai_server_log\server\tests\test_event_envelope.py`
  - Cover timestamp normalization, source metadata preservation, and duplicate event handling.
- Modify `C:\ai_server_log\agent\main.go`
  - Extend `LogPath` with source metadata fields.
  - Add source ID/relevance/classification helpers.
  - Add stable event UID in emitted events.
- Modify `C:\ai_server_log\agent\main_test.go`
  - Cover relevance-based candidate classification and stable event UID generation.

---

### Task 1: Server Log Source Registry

**Files:**
- Modify: `C:\ai_server_log\server\server\app\storage.py`
- Modify: `C:\ai_server_log\server\server\app\app.py`
- Create: `C:\ai_server_log\server\tests\test_log_sources.py`

**Interfaces:**
- Produces: `Store.upsert_log_source(source: dict[str, Any]) -> dict[str, Any]`
- Produces: `Store.list_log_sources(website_id: str | None = None, agent_id: str | None = None) -> list[dict[str, Any]]`
- Produces HTTP: `POST /api/log-sources`
- Produces HTTP: `GET /api/log-sources?website_id=<id>&agent_id=<id>`

- [ ] **Step 1: Write failing storage test**

Create `C:\ai_server_log\server\tests\test_log_sources.py`:

```python
import tempfile
import unittest
from pathlib import Path

from server.app.storage import Store


class LogSourceRegistryTests(unittest.TestCase):
    def test_upsert_log_source_is_website_isolated_and_updates_health(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()

            first = store.upsert_log_source(
                {
                    "website_id": "website_1",
                    "agent_id": "app01",
                    "source_id": "src_app01_var_log_app",
                    "name": "app log",
                    "path": "/var/log/myapp/app.log",
                    "source_type": "custom_app",
                    "service": "myapp",
                    "classification": "custom_app",
                    "confidence": 0.71,
                    "status": "readable",
                    "last_seen_at": "2026-07-17T00:00:00+00:00",
                    "metadata": {"reason": "process_reference"},
                }
            )
            store.upsert_log_source(
                {
                    "website_id": "website_2",
                    "agent_id": "app02",
                    "source_id": "src_app02_var_log_app",
                    "name": "app log",
                    "path": "/var/log/myapp/app.log",
                    "source_type": "custom_app",
                    "service": "myapp",
                    "classification": "custom_app",
                    "confidence": 0.68,
                    "status": "readable",
                    "last_seen_at": "2026-07-17T00:00:00+00:00",
                    "metadata": {},
                }
            )
            updated = store.upsert_log_source(
                {
                    "website_id": "website_1",
                    "agent_id": "app01",
                    "source_id": "src_app01_var_log_app",
                    "name": "app log",
                    "path": "/var/log/myapp/app.log",
                    "source_type": "custom_app",
                    "service": "myapp",
                    "classification": "custom_app",
                    "confidence": 0.91,
                    "status": "unreadable",
                    "last_seen_at": "2026-07-17T00:05:00+00:00",
                    "metadata": {"error": "permission denied"},
                }
            )

            sources = store.list_log_sources("website_1")

            self.assertEqual(first["source_id"], "src_app01_var_log_app")
            self.assertEqual(updated["status"], "unreadable")
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["website_id"], "website_1")
            self.assertEqual(sources[0]["agent_id"], "app01")
            self.assertEqual(sources[0]["confidence"], 0.91)
            self.assertEqual(sources[0]["metadata"]["error"], "permission denied")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run storage test and verify it fails**

Run:

```powershell
cd C:\ai_server_log\server
python -m unittest tests.test_log_sources -v
```

Expected: FAIL with `AttributeError: 'Store' object has no attribute 'upsert_log_source'`.

- [ ] **Step 3: Implement `log_sources` schema and storage methods**

In `Store.init()`, add:

```python
create table if not exists log_sources (
    source_id text primary key,
    website_id text not null,
    agent_id text not null,
    name text not null,
    path text not null,
    source_type text not null,
    service text not null,
    classification text not null,
    confidence real not null,
    status text not null,
    first_seen_at text not null,
    last_seen_at text not null,
    metadata_json text not null
);

create index if not exists idx_log_sources_website_agent
    on log_sources (website_id, agent_id);
create index if not exists idx_log_sources_status
    on log_sources (website_id, status);
```

Add methods:

```python
def upsert_log_source(self, source: dict[str, Any]) -> dict[str, Any]:
    source_id = str(source.get("source_id") or "").strip()
    website_id = str(source.get("website_id") or "").strip()
    agent_id = str(source.get("agent_id") or "").strip()
    path = str(source.get("path") or "").strip()
    if not source_id:
        raise ValueError("missing required log source field: source_id")
    if not website_id:
        raise ValueError("missing required log source field: website_id")
    if not agent_id:
        raise ValueError("missing required log source field: agent_id")
    if not path:
        raise ValueError("missing required log source field: path")

    name = str(source.get("name") or source_id)
    source_type = str(source.get("source_type") or source.get("type") or "candidate")
    service = str(source.get("service") or source_type)
    classification = str(source.get("classification") or source_type)
    confidence = float(source.get("confidence") or 0.0)
    status = str(source.get("status") or "unknown")
    last_seen_at = str(source.get("last_seen_at") or "")
    if not last_seen_at:
        raise ValueError("missing required log source field: last_seen_at")
    metadata_json = json.dumps(dict(source.get("metadata") or {}), sort_keys=True)

    with self._connect() as db:
        existing = db.execute(
            "select first_seen_at from log_sources where source_id = ?",
            (source_id,),
        ).fetchone()
        first_seen_at = str(existing["first_seen_at"]) if existing else last_seen_at
        db.execute(
            """
            insert into log_sources (
                source_id, website_id, agent_id, name, path, source_type, service,
                classification, confidence, status, first_seen_at, last_seen_at,
                metadata_json
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            on conflict(source_id) do update set
                website_id = excluded.website_id,
                agent_id = excluded.agent_id,
                name = excluded.name,
                path = excluded.path,
                source_type = excluded.source_type,
                service = excluded.service,
                classification = excluded.classification,
                confidence = excluded.confidence,
                status = excluded.status,
                last_seen_at = excluded.last_seen_at,
                metadata_json = excluded.metadata_json
            """,
            (
                source_id,
                website_id,
                agent_id,
                name,
                path,
                source_type,
                service,
                classification,
                confidence,
                status,
                first_seen_at,
                last_seen_at,
                metadata_json,
            ),
        )
    return self._log_source_by_id(source_id)

def list_log_sources(
    self,
    website_id: str | None = None,
    agent_id: str | None = None,
) -> list[dict[str, Any]]:
    query = "select * from log_sources"
    clauses: list[str] = []
    params: list[Any] = []
    if website_id:
        clauses.append("website_id = ?")
        params.append(website_id)
    if agent_id:
        clauses.append("agent_id = ?")
        params.append(agent_id)
    if clauses:
        query += " where " + " and ".join(clauses)
    query += " order by website_id, agent_id, name"
    with self._connect() as db:
        rows = db.execute(query, params).fetchall()
    return [self._log_source_row_to_dict(row) for row in rows]

def _log_source_by_id(self, source_id: str) -> dict[str, Any]:
    with self._connect() as db:
        row = db.execute("select * from log_sources where source_id = ?", (source_id,)).fetchone()
    if not row:
        raise ValueError(f"log source not found: {source_id}")
    return self._log_source_row_to_dict(row)

def _log_source_row_to_dict(self, row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
    return result
```

- [ ] **Step 4: Run storage test and verify it passes**

Run:

```powershell
cd C:\ai_server_log\server
python -m unittest tests.test_log_sources -v
```

Expected: PASS.

- [ ] **Step 5: Write failing HTTP API test**

Append to `C:\ai_server_log\server\tests\test_log_sources.py`:

```python
import json

from server.app.app import create_app


class LogSourceHttpTests(unittest.TestCase):
    def test_log_source_api_upserts_and_lists_sources_by_website(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            app = create_app(Path(temp_dir))
            payload = {
                "website_id": "website_1",
                "agent_id": "app01",
                "sources": [
                    {
                        "source_id": "src_app01_custom",
                        "name": "custom app",
                        "path": "/opt/shop/logs/app.log",
                        "source_type": "custom_app",
                        "service": "shop",
                        "classification": "custom_app",
                        "confidence": 0.82,
                        "status": "readable",
                        "last_seen_at": "2026-07-17T00:00:00+00:00",
                        "metadata": {"reason": "bounded_app_path"},
                    }
                ],
            }

            status, _headers, body = app.handle_json(
                "POST",
                "/api/log-sources",
                {},
                json.dumps(payload).encode("utf-8"),
            )
            list_status, _list_headers, list_body = app.handle_json(
                "GET",
                "/api/log-sources?website_id=website_1",
                {},
                b"",
            )

            response = json.loads(body.decode("utf-8"))
            sources = json.loads(list_body.decode("utf-8"))["sources"]
            self.assertEqual(status, 201)
            self.assertEqual(response["stored"], 1)
            self.assertEqual(list_status, 200)
            self.assertEqual(len(sources), 1)
            self.assertEqual(sources[0]["source_id"], "src_app01_custom")
            self.assertEqual(sources[0]["metadata"]["reason"], "bounded_app_path")
```

- [ ] **Step 6: Run HTTP test and verify it fails**

Run:

```powershell
cd C:\ai_server_log\server
python -m unittest tests.test_log_sources.LogSourceHttpTests -v
```

Expected: FAIL with `404` for `/api/log-sources`.

- [ ] **Step 7: Implement log source API**

In `AiLogApp.handle_json()`, add before the final 404:

```python
if method == "POST" and route == "/api/log-sources":
    return self._upsert_log_sources(body)
if method == "GET" and route == "/api/log-sources":
    website_id = (query.get("website_id") or [""])[0] or None
    agent_id = (query.get("agent_id") or [""])[0] or None
    return self._json(200, {"sources": self.store.list_log_sources(website_id, agent_id)})
```

Add method:

```python
def _upsert_log_sources(self, body: bytes) -> tuple[int, dict[str, str], bytes]:
    payload = json.loads(body.decode("utf-8"))
    website_id = str(payload.get("website_id") or "").strip()
    agent_id = str(payload.get("agent_id") or "").strip()
    sources = list(payload.get("sources") or [])
    if not website_id:
        raise ValueError("missing website_id")
    if not agent_id:
        raise ValueError("missing agent_id")
    stored = []
    for source in sources:
        item = dict(source)
        item["website_id"] = website_id
        item["agent_id"] = agent_id
        stored.append(self.store.upsert_log_source(item))
    return self._json(201, {"stored": len(stored), "sources": stored})
```

- [ ] **Step 8: Run API tests and full server tests**

Run:

```powershell
cd C:\ai_server_log\server
python -m unittest discover -s tests -v
```

Expected: all server tests pass.

---

### Task 2: Event Envelope Metadata and Timestamp Normalization

**Files:**
- Modify: `C:\ai_server_log\server\server\app\core.py`
- Modify: `C:\ai_server_log\server\server\app\storage.py`
- Create: `C:\ai_server_log\server\tests\test_event_envelope.py`

**Interfaces:**
- Produces: `normalize_timestamp(value: str, observed_at: str | None = None) -> tuple[str, str]`
- Extends event dict with `source_id`, `source_confidence`, `timestamp_confidence`, `event_uid`, `multiline`, and `line_count`.

- [ ] **Step 1: Write failing event envelope test**

Create `C:\ai_server_log\server\tests\test_event_envelope.py`:

```python
import tempfile
import unittest
from pathlib import Path

from server.app.core import classify_event, normalize_event
from server.app.storage import Store


class EventEnvelopeTests(unittest.TestCase):
    def test_normalize_event_preserves_source_and_timestamp_confidence(self):
        event = normalize_event(
            {
                "website_id": "website_1",
                "agent_id": "app01",
                "agent_role": "app",
                "timestamp": "not-a-real-time",
                "message": "Traceback line 1\n  line 2",
                "source_id": "src_app01_app",
                "source_confidence": 0.82,
                "event_uid": "uid-1",
                "multiline": True,
                "line_count": 2,
            },
            observed_at="2026-07-17T00:00:00+00:00",
        )

        self.assertEqual(event["source_id"], "src_app01_app")
        self.assertEqual(event["source_confidence"], 0.82)
        self.assertEqual(event["event_uid"], "uid-1")
        self.assertTrue(event["multiline"])
        self.assertEqual(event["line_count"], 2)
        self.assertEqual(event["timestamp"], "2026-07-17T00:00:00+00:00")
        self.assertEqual(event["timestamp_confidence"], "fallback_observed_at")

    def test_duplicate_event_uid_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            store = Store(Path(temp_dir) / "test.db")
            store.init()
            payload = {
                "website_id": "website_1",
                "agent_id": "app01",
                "agent_role": "app",
                "timestamp": "2026-07-17T00:00:00+00:00",
                "message": "connection refused",
                "event_uid": "uid-duplicate",
                "source_id": "src_app01_app",
            }
            event = classify_event(normalize_event(payload))

            first = store.ingest_event(event)
            second = store.ingest_event(event)

            self.assertEqual(first["event_id"], second["event_id"])
            self.assertEqual(store.count_events("website_1"), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run event envelope test and verify it fails**

Run:

```powershell
cd C:\ai_server_log\server
python -m unittest tests.test_event_envelope -v
```

Expected: FAIL because `source_id` or timestamp fallback fields are missing.

- [ ] **Step 3: Implement timestamp normalization and metadata preservation**

In `core.py`, add:

```python
def normalize_timestamp(value: str, observed_at: str | None = None) -> tuple[str, str]:
    text = str(value or "").strip()
    if text:
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).isoformat(), "parsed"
        except ValueError:
            pass
    return observed_at or utc_now_iso(), "fallback_observed_at"
```

In `normalize_event()`, use:

```python
normalized_timestamp, timestamp_confidence = normalize_timestamp(str(payload["timestamp"]), observed_at)
event_uid = str(payload.get("event_uid") or "")
event_basis = "|".join(
    [
        str(payload["website_id"]),
        str(payload["agent_id"]),
        event_uid or normalized_timestamp,
        message,
    ]
)
```

And add to returned dict:

```python
"timestamp": normalized_timestamp,
"timestamp_confidence": timestamp_confidence,
"source_id": payload.get("source_id"),
"source_confidence": float(payload.get("source_confidence") or 0.0),
"event_uid": event_uid or None,
"multiline": bool(payload.get("multiline", False)),
"line_count": int(payload.get("line_count") or 1),
```

- [ ] **Step 4: Persist source metadata in event metadata JSON**

In `storage.py`, ensure `_insert_event()` includes source metadata inside `metadata_json` by building metadata from the event's existing metadata plus:

```python
metadata = dict(event.get("metadata") or {})
for key in ("source_id", "source_confidence", "timestamp_confidence", "event_uid", "multiline", "line_count"):
    if event.get(key) is not None:
        metadata[key] = event.get(key)
```

Then store `json.dumps(metadata, sort_keys=True)`.

Make duplicate `event_id` inserts idempotent with `insert or ignore` or equivalent so retries do not fail.

- [ ] **Step 5: Run event envelope tests and full server tests**

Run:

```powershell
cd C:\ai_server_log\server
python -m unittest tests.test_event_envelope -v
python -m unittest discover -s tests -v
```

Expected: all server tests pass.

---

### Task 3: Agent Source Metadata and Stable Event UID

**Files:**
- Modify: `C:\ai_server_log\agent\main.go`
- Modify: `C:\ai_server_log\agent\main_test.go`

**Interfaces:**
- Produces: `sourceID(agentName string, path string) string`
- Produces: `classifyLogPath(path string, explicitType string) (classification string, confidence float64)`
- Extends `Event` JSON with `source_id`, `source_confidence`, and `event_uid`.

- [ ] **Step 1: Write failing Go tests**

Append to `C:\ai_server_log\agent\main_test.go`:

```go
func TestClassifyLogPathTreatsKnownServicesAsClassifiersNotWhitelist(t *testing.T) {
    classification, confidence := classifyLogPath("/opt/shop/logs/app.log", "")
    if classification != "custom_app" {
        t.Fatalf("expected custom_app classification, got %s", classification)
    }
    if confidence < 0.50 {
        t.Fatalf("expected useful confidence for custom app path, got %f", confidence)
    }

    classification, confidence = classifyLogPath("/var/log/nginx/error.log", "")
    if classification != "known_service" {
        t.Fatalf("expected known_service classification, got %s", classification)
    }
    if confidence < 0.80 {
        t.Fatalf("expected high confidence for nginx path, got %f", confidence)
    }
}

func TestSourceIDAndEventUIDAreStable(t *testing.T) {
    id1 := sourceID("app01", "/opt/shop/logs/app.log")
    id2 := sourceID("app01", "/opt/shop/logs/app.log")
    if id1 == "" || id1 != id2 {
        t.Fatalf("expected stable source id, got %q and %q", id1, id2)
    }

    event := buildEvent(Config{}, LogPath{Name: "app", Path: "/opt/shop/logs/app.log", Type: "custom_app"}, "2026-07-17T00:00:00Z", "connection refused")
    if event.EventUID == "" {
        t.Fatal("expected event uid")
    }
    if event.SourceID == "" {
        t.Fatal("expected source id")
    }
}
```

- [ ] **Step 2: Run Go tests and verify failure**

Run:

```powershell
cd C:\ai_server_log\agent
go test ./... -count=1
```

Expected: FAIL because helper functions and event fields do not exist.

- [ ] **Step 3: Implement agent metadata helpers**

In `main.go`, extend imports with:

```go
import "crypto/sha1"
```

Extend `LogPath`:

```go
Classification string  `yaml:"-"`
Confidence     float64 `yaml:"-"`
```

Extend `Event`:

```go
SourceID         string  `json:"source_id"`
SourceConfidence float64 `json:"source_confidence"`
EventUID         string  `json:"event_uid"`
```

Add:

```go
func sourceID(agentName string, path string) string {
    basis := fmt.Sprintf("%s|%s", agentName, filepath.Clean(path))
    sum := sha1.Sum([]byte(basis))
    return fmt.Sprintf("src_%x", sum[:10])
}

func classifyLogPath(path string, explicitType string) (string, float64) {
    text := strings.ToLower(filepath.ToSlash(path + " " + explicitType))
    known := []string{"nginx", "apache", "httpd", "mysql", "mariadb", "postgresql", "php", "redis", "haproxy"}
    for _, item := range known {
        if strings.Contains(text, item) {
            return "known_service", 0.90
        }
    }
    if strings.Contains(text, "/opt/") || strings.Contains(text, "/srv/") || strings.Contains(text, "/logs/") {
        return "custom_app", 0.65
    }
    if strings.Contains(text, "/var/log/") {
        return "system", 0.55
    }
    return "candidate", 0.35
}

func eventUID(agentName string, path string, timestamp string, message string) string {
    basis := fmt.Sprintf("%s|%s|%s|%s", agentName, filepath.Clean(path), timestamp, message)
    sum := sha1.Sum([]byte(basis))
    return fmt.Sprintf("evtuid_%x", sum[:12])
}
```

Add a `buildEvent()` helper and update `scanOnce()` to use it:

```go
func buildEvent(config Config, logPath LogPath, timestamp string, message string) Event {
    classification, confidence := classifyLogPath(logPath.Path, logPath.Type)
    agentName := config.Agent.Name
    return Event{
        WebsiteID:        config.Agent.WebsiteID,
        AgentID:          agentName,
        AgentRole:        config.Agent.Role,
        LogType:          logPath.Type,
        Service:          logPath.Type,
        FilePath:         logPath.Path,
        Timestamp:        timestamp,
        Message:          message,
        SourceID:         sourceID(agentName, logPath.Path),
        SourceConfidence: confidence,
        EventUID:         eventUID(agentName, logPath.Path, timestamp, message),
    }
}
```

- [ ] **Step 4: Run Go tests**

Run:

```powershell
cd C:\ai_server_log\agent
go test ./... -count=1
```

Expected: PASS.

---

### Task 4: Phase Verification

**Files:**
- No new files.

**Interfaces:**
- Verifies all phase 1 deliverables.

- [ ] **Step 1: Run full server tests**

Run:

```powershell
cd C:\ai_server_log\server
python -m unittest discover -s tests -v
```

Expected: all tests pass.

- [ ] **Step 2: Run full agent tests**

Run:

```powershell
cd C:\ai_server_log\agent
go test ./... -count=1
```

Expected: all tests pass.

- [ ] **Step 3: Verify plan coverage**

Check that Phase 1 now provides:

- Server source registry.
- Source metadata API.
- Event envelope metadata.
- Timestamp normalization.
- Idempotent event ingest retry behavior.
- Agent source classification helpers.
- Stable source IDs and event UIDs.

No git commit is performed because `C:\ai_server_log` is not a git repository.

---

## Later Plans

These are intentionally separate implementation plans:

- Phase 2: Agent offline spool, resend, server dedupe hardening, and loss markers.
- Phase 3: Multiline parser and bounded context windows.
- Phase 4: Dashboard Websites -> Website Map -> Machine -> Log Source.
- Phase 5: Incident memory model, evidence-based resolution, and repeated incident update policy.
- Phase 6: OpenAI-compatible AI contract and report schema.
- Phase 7: LINE/Google Chat notification engine.
- Phase 8: backup/restore CLI, update CLI, self-health, HTTPS, and token rotation.

