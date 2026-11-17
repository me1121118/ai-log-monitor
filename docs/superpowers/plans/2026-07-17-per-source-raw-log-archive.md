# Per-Source Raw Log Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add append-only raw JSONL log archives split by website, agent, source, and day.

**Architecture:** Keep SQLite as the query index and add a small server-side archive writer called from `/api/ingest` after a new event is inserted. `Store.ingest_event` reports whether an event was newly stored so duplicate retries do not write duplicate raw rows.

**Tech Stack:** Python standard library, existing `unittest`/`pytest` suite, SQLite store.

## Global Constraints

- Archive root is `<data_dir>/raw_logs`.
- Archive path shape is `raw_logs/<website>/<agent>/<source>/<YYYY-MM-DD>.jsonl`.
- Every path segment must be sanitized.
- Raw JSONL rows must include `event_id`, `website_id`, `agent_id`, `source_id`, `file_path`, `service`, `timestamp`, `observed_at`, `severity`, `category`, `fingerprint`, and `message`.
- Duplicate event retries must not append duplicate raw rows.
- Server must derive missing `source_id` from `agent_id + file_path` so older agents and newer agents share the same source archive.
- Server must suppress same-source near-duplicates within 30 seconds.

---

### Task 1: Add Archive Writer

**Files:**
- Create: `C:/ai_server_log/server/server/app/raw_archive.py`
- Test: `C:/ai_server_log/server/tests/test_raw_archive.py`

**Interfaces:**
- Produces: `archive_event(root: Path, event: dict[str, Any]) -> Path`
- Produces: `archive_path_for_event(root: Path, event: dict[str, Any]) -> Path`

- [ ] Write tests for safe path generation and JSONL append.
- [ ] Implement compact JSONL writing with parent directory creation.
- [ ] Run `python -m pytest server/tests/test_raw_archive.py -q`.

### Task 2: Make Ingest Idempotence Visible

**Files:**
- Modify: `C:/ai_server_log/server/server/app/core.py`
- Modify: `C:/ai_server_log/server/server/app/storage.py`
- Test: `C:/ai_server_log/server/tests/test_event_envelope.py`

**Interfaces:**
- Produces: `Store.ingest_event(...)` result includes `stored: bool`.
- Produces: `normalize_event(...)` derives missing `source_id` from `agent_id + file_path`.

- [ ] Extend duplicate-event test to assert first insert returns `stored=True` and duplicate returns `stored=False`.
- [ ] Add a legacy/source-aware dedupe test for the same `file_path`, timestamp, and message.
- [ ] Add a near-duplicate API test for same source/message with slightly different ingest timestamps.
- [ ] Update `normalize_event`.
- [ ] Update `Store.ingest_event`.
- [ ] Run `python -m pytest server/tests/test_event_envelope.py -q`.

### Task 3: Wire Archive Into API Ingest

**Files:**
- Modify: `C:/ai_server_log/server/server/app/app.py`
- Test: `C:/ai_server_log/server/tests/test_http_api.py`

**Interfaces:**
- Consumes: `archive_event(root, event)`.
- Consumes: `Store.ingest_event(...)[stored]`.

- [ ] Add API test that `/api/ingest` creates one source/day JSONL file.
- [ ] Add API test that duplicate ingest leaves one JSONL row.
- [ ] Call `archive_event(self.data_dir / "raw_logs", event)` only when `stored` is true.
- [ ] Run `python -m pytest server/tests/test_http_api.py -q`.

### Task 4: Verify And Deploy

**Files:**
- Use existing server and agent deployment files.

- [ ] Run full server tests.
- [ ] Run agent tests if agent envelope changes are suspected.
- [ ] Rebuild the server container.
- [ ] Deploy to `10.1.15.180`.
- [ ] Send a probe from `10.1.15.163`.
- [ ] Verify raw file exists under production `data-prod/raw_logs/website_1/db1/...`.
