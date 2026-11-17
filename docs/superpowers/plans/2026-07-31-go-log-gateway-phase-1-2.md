# Go Log Gateway Phase 1-2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a Go Gateway on public port 8888 without changing Agent behavior, then add shadow Log classification while Python remains authoritative.

**Architecture:** Phase 1 reverse proxies every request to the internal Python server and owns only Gateway health. Phase 2 inspects bounded single-event ingest bodies, computes a Go classification, forwards the original request unchanged, compares the Python response, and returns the Python response to the Agent. No persistence behavior changes in these phases.

**Tech Stack:** Go standard library (`net/http`, `httputil.ReverseProxy`, `httptest`), Python server on port 8889, Podman Compose, existing unittest and Go test suites.

## Global Constraints

- Expose only Go port `8888` to the LAN; Python port `8889` stays internal.
- Keep the existing Agent `server.url` and external API contract unchanged.
- Phase 1 forwards `/api/ingest` to Python; it never returns a synthetic success.
- Phase 2 shadow mode never changes the request forwarded to Python and never changes the response returned to the Agent.
- Strip inbound `X-Internal-Auth` before proxying.
- Bound request bodies, response bodies, header timeouts, idle timeouts, and upstream dial timeouts.
- Preserve cookies, query strings, status codes, response headers, and static file paths.
- Do not modify or delete the uncommitted Python fallback classifier/profile/parser work.

---

### Task 1: Gateway configuration and reverse proxy

**Files:**
- Create: `server/gateway/go.mod`
- Create: `server/gateway/internal/config/config.go`
- Create: `server/gateway/internal/proxy/proxy.go`
- Create: `server/gateway/internal/proxy/proxy_test.go`

**Interfaces:**
- `config.Load() (Config, error)` returns `ListenAddress`, `PythonBaseURL`, `UpstreamTimeout`, `ReadHeaderTimeout`, `IdleTimeout`, and `MaxInspectBodyBytes`.
- `proxy.New(target *url.URL, transport http.RoundTripper) http.Handler` returns a reverse proxy that strips inbound internal-auth headers and maps unavailable upstream responses to JSON `503`.

- [ ] **Step 1: Write failing proxy tests** using `httptest.Server` for query strings, request bodies, `Set-Cookie`, status codes, static paths, stripped `X-Internal-Auth`, and unavailable upstream `503`.
- [ ] **Step 2: Run `go test ./internal/proxy -count=1`** and verify failure because the package implementation is absent.
- [ ] **Step 3: Implement config and proxy** with `httputil.NewSingleHostReverseProxy`, a bounded transport, `ErrorHandler`, and no external Go dependencies.
- [ ] **Step 4: Run `go test ./internal/proxy ./internal/config -count=1`** and require success.
- [ ] **Step 5: Commit** with `feat: add bounded Go reverse proxy`.

### Task 2: Gateway router, health, and executable

**Files:**
- Create: `server/gateway/internal/router/router.go`
- Create: `server/gateway/internal/router/router_test.go`
- Create: `server/gateway/cmd/gateway/main.go`
- Create: `server/gateway/cmd/gateway/main_test.go`

**Interfaces:**
- `router.New(proxyHandler http.Handler, pythonHealthURL string, client *http.Client) http.Handler` owns `GET /health` and proxies all other routes, including `/api/ingest`.
- `GET /health` returns `200 {"status":"ok","python":"ok"}` when Python is reachable and `200 {"status":"degraded","python":"unavailable"}` when it is not.
- `main.run(ctx context.Context, cfg config.Config) error` starts and gracefully shuts down `http.Server`.

- [ ] **Step 1: Write failing router tests** proving `/health` is Gateway-owned while login, static, Agent registration, heartbeat, and ingest are forwarded unchanged.
- [ ] **Step 2: Run `go test ./internal/router ./cmd/gateway -count=1`** and confirm the missing implementation fails.
- [ ] **Step 3: Implement router and executable** with explicit server timeouts, signal-aware shutdown, and no ingest stub.
- [ ] **Step 4: Run `go test ./... -count=1`, `go vet ./...`, and `go build ./cmd/gateway`**.
- [ ] **Step 5: Commit** with `feat: add Go gateway routing and health`.

### Task 3: Container and Compose routing

**Files:**
- Create: `server/gateway/Containerfile`
- Modify: `server/Containerfile`
- Modify: `server/compose.yaml`
- Modify: `server/server/main.py`
- Test: `scripts/container_smoke.py`

**Interfaces:**
- Gateway environment: `GATEWAY_LISTEN_ADDRESS=:8888`, `PYTHON_BASE_URL=http://ai-log-server:8889`.
- Python environment: `AI_LOG_HOST=0.0.0.0`, `AI_LOG_PORT=8889`.
- Compose publishes only `8888:8888` from `ai-log-gateway`; `ai-log-server` uses `expose: 8889` without a host port.

- [ ] **Step 1: Extend smoke assertions** to require both services, only one published LAN port, and Gateway-to-Python health.
- [ ] **Step 2: Run the smoke test** and verify failure because Gateway service/container files are absent.
- [ ] **Step 3: Add multi-stage Gateway image and Compose service** while preserving Server secrets/data volumes and existing container names where tests require them.
- [ ] **Step 4: Build and start with Podman Compose**, then verify `/health`, `/login`, `/static/css/styles.css`, Agent registration, heartbeat, and one ingest request through port 8888.
- [ ] **Step 5: Commit** with `feat: route server traffic through Go gateway`.

### Task 4: Go source profiles and parsers

**Files:**
- Create: `server/gateway/internal/profile/profile.go`
- Create: `server/gateway/internal/profile/profile_test.go`
- Create: `server/gateway/internal/parser/parser.go`
- Create: `server/gateway/internal/parser/parser_test.go`

**Interfaces:**
- `profile.ProfileSource(EventSource) SourceProfile` returns `ServiceClass`, `SourceKind`, and `TrafficCandidate`.
- `parser.ParseSignalFields(EventInput) ParsedFields` returns optional `StatusCode`, `RequestMethod`, `RequestPath`, `LatencyMS`, and `DatabaseErrorCode`.

- [ ] **Step 1: Port the Python golden cases into failing Go table tests** for Nginx access/error, HAProxy journal, MariaDB error, syslog, auth, HTTP request parsing, latency, DB error code, and explicit status precedence.
- [ ] **Step 2: Run `go test ./internal/profile ./internal/parser -count=1`** and confirm missing implementations fail.
- [ ] **Step 3: Implement bounded profile and parser functions** using compiled Go regexes and an 8 KiB message inspection cap.
- [ ] **Step 4: Run the focused tests plus Python profile/parser tests** and compare every golden result.
- [ ] **Step 5: Commit** with `feat: add Go log profiles and parsers`.

### Task 5: Shadow classifier

**Files:**
- Create: `server/gateway/internal/classifier/types.go`
- Create: `server/gateway/internal/classifier/classifier.go`
- Create: `server/gateway/internal/classifier/classifier_test.go`
- Create: `server/gateway/internal/shadow/handler.go`
- Create: `server/gateway/internal/shadow/handler_test.go`
- Modify: `server/gateway/internal/router/router.go`

**Interfaces:**
- `classifier.Classify(EventInput) ClassificationResult` returns `SignalType`, `Severity`, `Category`, `RuleID`, `Confidence`, and `Basis`.
- `shadow.New(next http.Handler, classifier Classifier, metrics Comparator) http.Handler` inspects only bounded JSON `POST /api/ingest` requests, restores the original body, records comparison counters, and returns the unchanged Python response.
- Oversized, batched, malformed, or non-JSON requests bypass shadow inspection and still proxy to Python.

- [ ] **Step 1: Write failing classifier golden tests** matching the Python fallback for traffic success, upstream timeout, MariaDB connection exhaustion, kernel OOM, auth failure, warning retry, and unknown normal.
- [ ] **Step 2: Write failing shadow handler tests** proving byte-for-byte request forwarding, unchanged response, mismatch counter increments, and safe bypass behavior.
- [ ] **Step 3: Implement classifier and shadow middleware** without logging full messages or tokens.
- [ ] **Step 4: Run `go test -race ./...`, Python classifier tests, and contract comparison tests**.
- [ ] **Step 5: Commit** with `feat: add shadow Go log classification`.

### Task 6: Phase 1-2 verification checkpoint

**Files:**
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-31-go-log-gateway-phase-1-2.md` checkbox statuses

**Interfaces:**
- Existing Agent and browser behavior remains externally compatible through `http://server:8888`.
- Shadow mismatch metrics are observable in Gateway health without exposing Log messages.

- [ ] **Step 1: Run all Python Server tests and Agent installer tests**.
- [ ] **Step 2: Run Agent and Gateway `go test -race`, `go vet`, and builds**.
- [ ] **Step 3: Run Podman smoke checks and restart both containers** to verify persistence and automatic recovery.
- [ ] **Step 4: Simulate concurrent requests from at least 50 logical Agents** and confirm bounded memory, no race findings, and unchanged Python persistence counts.
- [ ] **Step 5: Review tracked files for secrets/runtime data and commit** with `chore: verify Go gateway shadow mode`.

## Self-Review

- Phase 1 cannot lose Agent token validation because ingest still reaches Python unchanged.
- Phase 2 cannot alter persistence because shadow middleware returns Python's response and forwards the original body.
- Login cookies, static files, query strings, uploads, and unavailable-upstream behavior have explicit tests.
- The plan defers evidence-only routing, RAM ownership, Traffic Monitor, and disk spool until shadow parity is measured.
- Python fallback files remain part of the contract comparison and are not removed.
