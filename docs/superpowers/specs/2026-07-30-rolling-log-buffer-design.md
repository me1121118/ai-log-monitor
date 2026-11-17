# Rolling Log Buffer Design

## Goal

Keep routine log traffic out of persistent storage while preserving enough recent context to explain a real problem.

## Behavior

- Classified `normal` events are stored only in server RAM.
- RAM entries are isolated by `website_id`, `agent_id`, and `source_id`.
- Each source keeps at most 200 events and at most five minutes of history.
- A `warning`, `problem`, or `critical` event is persisted as before.
- When a non-normal event arrives, up to 20 preceding events from the same source are copied into `metadata.context_before` before persistence.
- Normal events never create SQLite rows, incidents, or raw JSONL archive files.
- Restarting the server intentionally clears routine context.

## Safety

The buffer is guarded by a lock because the HTTP server handles requests concurrently. Limits apply independently to every source, and context never crosses a website or agent boundary.
