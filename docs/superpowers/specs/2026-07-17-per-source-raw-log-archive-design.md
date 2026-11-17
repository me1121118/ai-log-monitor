# Per-Source Raw Log Archive Design

## Goal

Store every accepted log event in two separated forms: the existing database rows for fast dashboard/API queries, and append-only raw JSONL files split by website, agent, source, and day.

## Scope

- The server owns raw archive persistence.
- The agent continues sending one event at a time with `source_id`, `file_path`, `log_type`, and `service`.
- Raw files are created under the server data directory at `raw_logs/<website>/<agent>/<source>/<YYYY-MM-DD>.jsonl`.
- Folder names must be sanitized so a hostile or unusual log path cannot escape `raw_logs`.
- The JSONL payload keeps the original event context, including real `file_path` and `source_id`.
- Duplicate event retries must not append duplicate raw rows.
- If an older agent sends `file_path` without `source_id`, the server derives the same stable `source_id` formula used by the Go agent: `sha1(agent_id|clean_file_path)`.
- Events from an older source-unaware agent and a newer source-aware agent for the same file, timestamp, and message must dedupe to one stored event and one raw archive row.
- If two running agents send the same normalized message from the same website, agent, and source within 30 seconds, the server treats the later event as a near-duplicate and skips a second DB/raw insert.
- Default retention remains outside this change; the archive layout is ready for a later raw retention task.

## Data Flow

1. Agent discovers log files and sends events with source metadata.
2. Server normalizes and classifies the event.
3. Server fills missing `source_id` from `agent_id + file_path` when possible.
4. Store inserts the event idempotently into SQLite.
5. If the event was newly inserted, server appends one compact JSON line to the matching raw archive file.
6. If the event already existed, server returns the same event id and skips raw append.

## Archive Layout

Example:

```text
data/
  raw_logs/
    website_1/
      db1/
        syslog--src_abc12345/
          2026-07-17.jsonl
        mysql-error.log--src_def67890/
          2026-07-17.jsonl
```

The source folder uses a readable base from `log_type`, `service`, or `file_path`, plus a short source id suffix when present. This keeps folders human-readable while avoiding collisions between files with the same basename.

## Testing

- Unit test the archive path sanitizer with dangerous website, agent, and source names.
- API test `/api/ingest` writes one JSONL row to the expected source/day file.
- API test duplicate ingest does not append a second raw row.
