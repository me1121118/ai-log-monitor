# AI Log Investigator Phase 3 Multiline Log Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep stack traces and multiline errors together as one event so AI receives coherent log context.

**Architecture:** Add lightweight generic multiline grouping to the Go agent. The agent groups complete lines per source before event construction, marks grouped events with `multiline` and `line_count`, and keeps existing unfinished-line offset behavior.

**Tech Stack:** Go stdlib tests and existing Python server envelope support.

## Global Constraints

- Preserve complete log context without aggressively filtering.
- Do not emit unfinished trailing lines.
- Keep source metadata and stable event IDs from Phase 1.
- Keep offline spool behavior from Phase 2.
- Avoid source-specific complexity in this phase; add generic stack trace heuristics first.

---

## File Structure

- Modify `C:\ai_server_log\agent\main.go`
  - Add `LogRecord`.
  - Add `groupLogLines(lines []string, maxLines int) []LogRecord`.
  - Extend `Event` with `multiline` and `line_count`.
  - Update `scanOnce()` to group complete lines before building events.
- Modify `C:\ai_server_log\agent\main_test.go`
  - Add grouping tests.
  - Add scanOnce integration test for stack trace grouping.

---

### Task 1: Generic Multiline Grouping

**Interfaces:**
- `type LogRecord struct { Message string; Multiline bool; LineCount int }`
- `groupLogLines(lines []string, maxLines int) []LogRecord`

**Steps:**
- [ ] Write failing tests for traceback grouping and normal line separation.
- [ ] Implement grouping helper.
- [ ] Run Go test binary.

---

### Task 2: scanOnce Integration

**Interfaces:**
- `buildEvent(config Config, logPath LogPath, timestamp string, record LogRecord) Event`
- `Event.Multiline bool`
- `Event.LineCount int`

**Steps:**
- [ ] Write failing scanOnce integration test.
- [ ] Update `buildEvent()` and `scanOnce()`.
- [ ] Run Go test binary, `go vet`, and server tests.

