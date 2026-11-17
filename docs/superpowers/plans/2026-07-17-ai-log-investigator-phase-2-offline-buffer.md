# AI Log Investigator Phase 2 Offline Buffer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make agent delivery resilient when the central server or LAN is unavailable, while ensuring retried events do not inflate server incidents.

**Architecture:** Harden server ingest idempotency first, then add a file-backed JSONL spool to the Go agent. The agent tries to flush stored events before sending new events; failed events remain on disk, successful sends are removed, and bounded-spool overflow creates an explicit loss marker.

**Tech Stack:** Python stdlib `unittest` and `sqlite3`, Go stdlib file IO/JSON, existing server and agent tests.

## Global Constraints

- `website_id` remains the hard isolation key.
- Delivery is at-least-once; duplicated retries must not create duplicate stored events or inflate incident counts.
- Agent state must survive process restart using files under `runtime.state_dir`.
- If events are dropped because a bounded buffer is full, the agent must create a visible loss marker event.
- No remote shell or remote command execution.
- `C:\ai_server_log` is not currently a git repository, so commits are replaced by verification checkpoints.

---

## File Structure

- Modify `C:\ai_server_log\server\server\app\storage.py`
  - Check duplicate event IDs before incident grouping.
- Modify `C:\ai_server_log\server\server\app\core.py`
  - Classify agent loss marker events.
- Create or modify `C:\ai_server_log\server\tests\test_reliability.py`
  - Cover duplicate problem ingest and loss marker classification.
- Modify `C:\ai_server_log\agent\main.go`
  - Add runtime `spool_max_bytes`.
  - Add JSONL spool append/load/replace helpers.
  - Add flush helper with injectable sender.
  - Wire main loop to flush before sending and spool failed sends.
- Modify `C:\ai_server_log\agent\main_test.go`
  - Cover spool persistence, partial flush, and bounded overflow loss marker.

---

### Task 1: Server Retry Idempotency and Loss Marker Classification

**Interfaces:**
- `Store.ingest_event(event)` returns the existing incident ID for duplicate `event_id`.
- `classify_event()` classifies messages containing `agent_spool_loss_marker` as `problem` / `agent_data_loss`.

**Steps:**
- [ ] Write failing tests in `tests/test_reliability.py`.
- [ ] Run only reliability tests and verify failure.
- [ ] Implement duplicate pre-check in `Store.ingest_event()`.
- [ ] Implement loss marker classification in `core.py`.
- [ ] Run reliability tests and full server tests.

---

### Task 2: Agent File-backed Spool Helpers

**Interfaces:**
- `spoolPath(stateDir string) string`
- `loadSpoolEvents(stateDir string) ([]Event, error)`
- `replaceSpoolEvents(stateDir string, events []Event) error`
- `appendSpoolEvent(stateDir string, event Event, maxBytes int64) error`
- `newLossMarkerEvent(config Config, dropped int, reason string) Event`

**Steps:**
- [ ] Write failing Go tests for spool persistence and overflow marker.
- [ ] Run `go test ./... -count=1` and verify failure.
- [ ] Implement spool helpers.
- [ ] Run Go tests.

---

### Task 3: Agent Flush and Main Loop Wiring

**Interfaces:**
- `flushSpoolEvents(stateDir string, sender func(Event) error) (int, error)`
- Main loop flushes spool before sending new scan results.
- Failed new sends are appended to spool.

**Steps:**
- [ ] Write failing Go test for partial flush keeping unsent events.
- [ ] Run Go tests and verify failure.
- [ ] Implement `flushSpoolEvents`.
- [ ] Wire main loop to call `flushSpoolEvents` and spool failed sends.
- [ ] Run Go tests and `go vet`.

---

### Task 4: Phase Verification

**Commands:**

```powershell
cd C:\ai_server_log\server
python -m unittest discover -s tests -v

cd C:\ai_server_log\agent
go test ./... -count=1
go vet ./...
python -m unittest discover -s tests -v
```

Expected: all tests pass.

