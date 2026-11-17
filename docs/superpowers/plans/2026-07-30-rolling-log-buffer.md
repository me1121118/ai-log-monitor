# Rolling Log Buffer Implementation Plan

1. Add an HTTP-level regression test proving a normal event is buffered without persistent storage.
2. Add unit tests for source isolation, entry limits, and age expiry.
3. Implement a thread-safe bounded rolling buffer.
4. Route normal ingest to RAM and attach same-source context to non-normal events.
5. Run focused tests, then the full server and agent verification suites.
6. Ask OpenCode to review the final diff and address valid findings.

