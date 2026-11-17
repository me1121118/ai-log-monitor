# Self-hosted AI Log Investigator Design

Date: 2026-07-17
Status: Draft for user review

## Summary

Self-hosted AI Log Investigator is a LAN-focused log analysis product that customers install inside their own environment. A central Linux + Podman server receives logs from Linux agents installed on web, application, database, load balancer, and worker machines. The system continuously reads logs, detects critical incidents, analyzes the affected website as a connected system, sends concise alerts through configured chat channels, and stores per-website incident memory so repeated problems can be recognized faster.

The first complete version is a full LAN production product, not a full SIEM and not a short MVP. It should be usable in a real customer LAN while avoiding unnecessary scope such as SaaS tenancy, billing, remote shell control, or auto-fix actions.

## Goals

- Installable by customers in their own LAN.
- Support multiple websites on one central server.
- Keep each website isolated by `website_id`.
- Require minimal agent configuration: server URL, website ID, agent name, and enrollment token.
- Automatically discover common Linux service logs and topology hints.
- Preserve enough log context for AI analysis instead of aggressively filtering logs.
- Preserve continuity during temporary network or central server outages.
- Analyze critical incidents immediately.
- Build long-term per-website incident memory after every resolved incident.
- Notify administrators through global notification channels such as LINE and Google Chat.
- Provide a simple Dashboard flow: Websites -> Website Map -> Machine -> Log Source.
- Support OpenAI-compatible AI APIs, including cloud and local model gateways.

## Non-goals

- Cloud SaaS multi-tenant hosting.
- Billing, licensing, or customer account management.
- Complex multi-user permission system.
- Full SIEM query language.
- Remote shell, remote command execution, or automatic service restart.
- Auto-fix actions.
- Windows agents in the first complete version.
- Per-website notification routing in the first complete version.
- Automatic silent updates.

## Target Environment

Central server:

- Linux host.
- Podman runtime.
- LAN-accessible HTTP endpoint.
- One admin user.
- Supported first: Ubuntu 22.04/24.04 LTS, Debian 12, Rocky Linux 9, AlmaLinux 9, and RHEL-compatible 9 hosts.
- Requires systemd and Podman 4 or newer.

Agents:

- Linux machines.
- Installed as privileged `systemd` services.
- Able to read service config, `/var/log`, and journal data where available.
- Supported first: Ubuntu 22.04/24.04 LTS, Debian 12, Rocky Linux 9, AlmaLinux 9, and RHEL-compatible 9 hosts.
- Requires systemd.

Initial scale target:

- 1 central server.
- 10-30 websites.
- 50-200 agents.
- Raw log retention default: 24 hours.

## High-level Architecture

```text
Linux Agent
  -> Ingest API
  -> Event Store
  -> Classifier
  -> Incident Builder
  -> Website Correlator
  -> Redactor / Summarizer
  -> AI Analyst
  -> Report + Per-website Memory
  -> Notification
```

`website_id` is the hard isolation key. Logs, machines, incidents, topology, reports, and memory must always be scoped by `website_id`.

## Central Server

The central server is installed as a Linux + Podman appliance.

Standard paths:

- `/opt/ai-log-investigator` for application files.
- `/etc/ai-log-investigator` for configuration.
- `/var/lib/ai-log-investigator` for database, event store, reports, and memory.
- `/var/log/ai-log-investigator` for product runtime logs.

Core responsibilities:

- Serve Dashboard.
- Manage websites and agent enrollment.
- Receive logs and agent health data.
- Store raw logs for short retention.
- Detect and group incidents.
- Maintain website topology and machine registry.
- Run AI investigations.
- Store reports and incident memory.
- Send notifications.
- Monitor its own health.
- Provide backup, restore, and update commands.

## Storage Strategy

The central server should separate durable metadata from high-volume raw log data.

Recommended first complete version:

- PostgreSQL container for websites, agents, source metadata, incidents, event indexes, reports, topology, notification history, and incident memory.
- Append-only raw log segment files under `/var/lib/ai-log-investigator` for short-retention raw log lines.
- Database indexes that point from incidents and event summaries to raw log time ranges.
- Background retention worker that expires raw log segments after the configured retention window.

Raw log storage rules:

- Default raw retention is 24 hours.
- Raw logs are kept per `website_id`, agent, source, and time range.
- Raw log deletion must not delete incident reports or incident memory.
- Raw logs are excluded from backup by default.

Metadata and memory rules:

- Incident memory, topology, reports, and registry data are durable.
- These are included in backup by default.
- All records that belong to a website must include `website_id`.

SQLite may be used only for local development or very small lab mode. The production appliance should use PostgreSQL.

## Agent

The Linux agent runs as a privileged `systemd` service. It is designed to feel like "install and it finds the useful logs by itself."

Minimal user-managed config:

```yaml
server_url: http://10.1.0.10:8080
website_id: shop-main
agent_name: app01
enroll_token: "<token>"
```

Agent-managed state:

- Discovered services.
- Discovered log paths.
- Discovered candidate log sources and relevance scores.
- File offsets.
- Source health.
- Topology hints.
- Agent identity after enrollment.

Agent responsibilities:

- Register itself with the central server.
- Discover relevant log sources automatically without requiring the product to be pre-locked to a fixed program list.
- Use known services such as nginx, Apache, MySQL, MariaDB, PostgreSQL, and PHP-FPM as high-confidence classifiers, not as the only supported sources.
- Scan bounded standard locations, service units, running processes, listening ports, and config references to find logs that are related to this machine's role.
- Read service config where safe and useful to discover true log paths and dependency hints.
- Tail discovered logs continuously.
- Preserve context; do not only send error lines.
- Send logs in micro-batches.
- Buffer unsent events locally when the central server or LAN is unavailable.
- Apply rate limits and backpressure without silently losing important incident context.
- Skip binary, compressed old archives, and unreadable files safely.
- Report unreadable files as health issues instead of crashing.
- Send source metadata such as path, service type, size, mtime, and read status.
- Send topology hints such as nginx upstreams, proxy targets, DB host/port references, and listening service ports.

Security boundaries:

- No remote shell.
- No arbitrary remote command execution.
- No dashboard action that directly runs commands on agent machines.
- Tokens and secrets must not be printed in logs.
- Sensitive content must be redacted before AI analysis and chat notification.

## Log Discovery

Discovery should be relevance-based. The agent should not be limited to a hardcoded list of supported programs. It should find likely log sources first, then classify them using service signatures, file metadata, process information, config references, and path patterns.

This is not unbounded whole-disk scanning. Discovery should use bounded, safe search areas and explicit signals:

- Standard log locations such as `/var/log`.
- Application locations such as `/opt/*/logs`, `/srv/*/logs`, and `/home/*/logs` when readable.
- systemd units and journal metadata.
- Running processes and listening ports.
- Service config files that point to log paths.
- Recently written text log files with log-like names and formats.

Known service examples are classifiers and shortcuts:

- nginx: inspect `nginx -T` or config files for `access_log`, `error_log`, `proxy_pass`, and upstreams.
- Apache: inspect config for `ErrorLog`, `CustomLog`, and proxy directives.
- MySQL/MariaDB: inspect config for error log, slow query log, and service identity.
- PostgreSQL: inspect config for log directory and filename patterns.
- PHP-FPM: inspect pool and runtime log paths.
- systemd: collect relevant journal sources where configured.
- Custom apps: scan bounded common paths such as `/opt/*/logs`, `/srv/*/logs`, and configured app paths.

Every discovered source should receive a classification and confidence level, for example:

- `known_service`: matched a known service signature.
- `custom_app`: likely application log from app paths or process references.
- `system`: system or journal source.
- `candidate`: log-like source found but not confidently classified yet.

The Dashboard should show these sources and allow the admin to disable noisy or irrelevant sources, but initial discovery should not require manual selection.

The agent should send both structured extracted hints and small redacted config snippets when useful for AI analysis. It must not send secrets such as passwords, API keys, private keys, tokens, or full sensitive config dumps.

## Reliability, Buffering, and Backpressure

The system should continue operating when the network, central server, AI provider, or notification channel is temporarily unavailable.

Agent buffering:

- Agent keeps a bounded local spool for unsent events.
- Spool survives agent restart.
- Delivery is at-least-once; events need stable IDs so the server can deduplicate retries.
- When the spool is near full, the agent prioritizes critical/error context and recent timeline continuity.
- If data must be dropped due to hard disk limits, the agent records a loss marker with source, time range, reason, and approximate dropped count.

Server backpressure:

- Ingest API accepts micro-batches.
- Server can tell agents to slow down per agent or source.
- Server keeps ingest separate from AI analysis so AI slowness does not block log ingestion.
- Incident detection should run from stored events, not directly from AI responses.

Rate limiting:

- Rate limits are per agent and per source.
- Known noisy sources such as high-volume access logs can be sampled or summarized only when the system is under pressure.
- Critical/error lines and nearby context have higher priority than routine info/access lines.
- The Dashboard should show when rate limiting or loss markers occurred.

AI and notification failures:

- If AI is unavailable, incidents remain stored as pending analysis.
- If notification sending fails, the system retries with backoff and records delivery state.
- Failed notification delivery must not block ingestion or incident grouping.

## Time and Timestamp Normalization

Reliable cross-machine analysis requires normalized time.

Rules:

- Store all event timestamps in UTC internally.
- Preserve original timestamp text and source timezone when available.
- Record agent receive time and server ingest time separately.
- Detect clock skew between agent time and server time.
- Surface clock skew in Dashboard when it can affect incident timelines.
- Recommend NTP or chrony on all central and agent machines.

When a log line has no parseable timestamp, the agent should use file read time as a fallback and mark timestamp confidence as low.

AI timeline generation must prefer high-confidence parsed timestamps, then fallback timestamps, and should mention time uncertainty when relevant.

## Multiline Log Handling

The agent and server must support multiline log events.

Examples:

- Python, PHP, Java, and Node stack traces.
- SQL errors spanning multiple lines.
- Application exception blocks.
- Kernel or service logs that continue on indented lines.

Rules:

- Multiline grouping should use source-specific heuristics when known.
- Generic fallback should treat lines without a timestamp or with indentation as continuations where appropriate.
- Grouped events must retain original lines.
- The system should avoid splitting stack traces into unrelated incidents.
- Very large multiline events should be bounded and marked as truncated with line counts.

## Dashboard

The Dashboard is organized around websites, not raw logs.

Navigation:

```text
Websites
  -> Website Map / Machines
  -> Machine Detail
  -> Log Source Detail
```

Websites page:

- Website name and ID.
- Overall status.
- Number of machines.
- Online/offline agents.
- Latest incident summary.

Website Map page:

- Machines in the selected website.
- Machine roles such as `lb`, `web`, `app`, `db`, `cache`, and `worker`.
- Topology/dependency map.
- Status of each machine.
- Active and recent incidents.
- Manual topology override editor.
- Run AI Investigation action.

Machine Detail page:

- Hostname, IP, role, agent version, last seen.
- Detected services.
- Log sources and read health.
- Recent log preview.
- Per-machine analysis action.

Log Source Detail page:

- Source metadata.
- Recent log lines.
- Filters for level, service, time, and incident relation.
- Read status and discovery details.

## Topology

The system should infer website topology automatically first, then allow admin correction in the Dashboard.

Topology sources:

- nginx upstream and proxy config.
- Apache proxy config.
- App config hints after redaction.
- Database host/port references.
- Agent-discovered listening ports.
- Log evidence showing repeated connections between machines.
- Manual admin overrides.

Topology edge confidence:

- `discovered`: directly found in config or service data.
- `inferred`: derived from logs or repeated behavior.
- `manual`: set by admin; manual overrides win over auto-discovery.

AI investigation must use topology when reasoning about root cause and impact. For example, if DB errors start before app timeouts and nginx 502s, the report should distinguish likely DB root cause from downstream HTTP symptoms.

## Retention and Memory

Raw logs:

- Default retention: 24 hours.
- Optional economy mode: 12 hours.
- Raw logs are not included in backups by default.

Event summaries:

- Stored longer than raw logs.
- Capture important counts, patterns, severity changes, affected machines, and timeline summaries.

Incident memory:

- Created after every resolved incident.
- Stored per `website_id`.
- Not mixed across websites.
- Used to recognize repeated patterns quickly.

Incident memory contains:

- Website ID.
- Fingerprint.
- First and last seen times.
- Affected machines and roles.
- Related log sources.
- Suspected causes.
- Evidence patterns.
- Recovery evidence.
- Topology path.
- Confidence.
- Status such as `suspected`, `confirmed`, `recovered_by_log_evidence`, or `recovered_unknown_fix`.

Memory usage rule:

- Confirmed memory has higher weight.
- Suspected memory is a hint, not proof.
- Current logs must be checked before concluding that a new incident is the same as a past incident.

## Incident Detection and Grouping

Critical incidents are analyzed immediately.

Repeated matching events must be grouped into the same incident when they share:

- Same `website_id`.
- Similar fingerprint or pattern.
- Related machines/log sources.
- Same active time window.

The system should avoid notification spam:

- First critical occurrence sends notification.
- Repeated events update the existing incident.
- Updates are sent only when important facts change, such as new affected machines, severity increase, or changed suspected root cause.

Resolution:

- The system resolves incidents based on log evidence, not only elapsed time.
- Evidence can include error pattern stopping, success logs returning, status logs showing readiness, and error rates returning near baseline.
- Time windows such as 15 minutes are used as stabilization guards, not the primary proof.
- No resolved notification is sent to LINE or Google Chat by default.

Every resolved incident creates memory.

## AI Analysis

AI integration uses an OpenAI-compatible API.

Provider config:

```yaml
ai_provider:
  base_url: http://localhost:11434/v1
  api_key: optional
  model: local-model-name
```

or:

```yaml
ai_provider:
  base_url: https://api.openai.com/v1
  api_key: "<secret>"
  model: "<model>"
```

The system must keep its AI contract stable regardless of provider.

AI input package:

- System prompt defining the AI as a site reliability log analyst.
- Task prompt for the current job.
- Website ID.
- Website topology.
- Machine registry.
- Current incident details.
- 30-minute default log window, configurable per policy.
- Similar incident memory from the same website only.
- Redacted config snippets and service hints where useful.

AI output schema:

- Summary.
- Severity.
- Suspected root causes.
- Evidence for each suspected cause.
- Affected machines.
- Timeline.
- Relation to previous incidents.
- Confidence.
- Recommended next checks.
- Notification summary.
- Memory candidate.

The number of suspected causes is not fixed. AI should list as many as evidence supports, ordered by likelihood and usefulness.

Failure behavior:

- If AI is unavailable, ingestion continues.
- Incidents remain stored.
- Dashboard shows analysis pending or failed.
- Analysis can be retried later.

## Analysis Policy

Policies can be configured globally and, where useful, per website.

Defaults:

- Language: selectable; Thai is the expected default for this deployment style.
- Critical: analyze immediately.
- Warning: batch or defer.
- Analysis window: 30 minutes.
- Raw log retention: 24 hours.
- Notifications: enabled for critical.
- Resolved notifications: disabled.

Language:

- Report language is selectable.
- Notification language follows the configured report language.

## Notifications

Notification channels are global in the first complete version.

Supported channels:

- LINE.
- Google Chat.
- Generic webhook can be added later.

Notifications must identify the website clearly, so per-website channel routing is not required in the first version.

Critical notification content:

- Website.
- Starting machine or primary affected machine.
- Role.
- Log source.
- Short abnormal log summary.
- Suspected causes, with top causes shown first.
- Confidence where available.
- Link to full Dashboard report.

If there are many suspected causes, chat notifications should show the most important ones and link to the full report.

Resolved notifications are not sent by default.

## System Self-health

The product must monitor itself, not only customer application logs.

Central health signals:

- Disk usage and projected retention risk.
- PostgreSQL/container health.
- Ingest queue depth.
- AI queue depth and failed analyses.
- Notification delivery failures.
- Backup success/failure.
- Update state.
- Clock skew warnings from agents.

Agent health signals:

- Last seen time.
- Agent version.
- Local spool usage.
- Discovered source count.
- Unreadable source count.
- Rate limit or loss markers.
- CPU and memory pressure where available.
- Service restart count.

Dashboard should show these health signals clearly so an admin can distinguish product health problems from website incidents.

## Authentication

Dashboard authentication starts with a single admin user.

Admin can:

- Manage websites.
- Generate agent install commands.
- View machines.
- View log sources.
- View and adjust topology.
- Configure AI provider.
- Configure notifications.
- View reports and memory.
- Run backup, restore guidance, and update guidance.

The first version does not include multiple users, roles, or detailed permission controls.

## Installation

Central server installer:

- Installs or verifies Podman.
- Creates configuration folders.
- Creates data folders.
- Generates or asks for admin credentials.
- Starts containers through systemd-managed Podman units.
- Prints Dashboard URL.

Agent installer:

- Installs agent binary or package.
- Writes minimal config.
- Registers with central server using enrollment token.
- Starts privileged systemd service.
- Reports discovered logs and health.

The Dashboard should be able to generate an agent install command containing the selected `website_id`, server URL, and token.

## Backup and Restore

Backup/restore is included in the first complete version as CLI.

Commands:

```text
ai-logctl backup
ai-logctl restore <backup-file>
```

Included by default:

- Database/event store metadata.
- Incident memory.
- Reports.
- Website and machine registry.
- Topology and manual overrides.
- Non-secret configuration.

Excluded by default:

- Raw logs.
- Plain secrets.
- API keys.
- Webhook secrets.
- Enrollment tokens.

Restore must preserve the boundary between restored config and machine-specific secrets that need to be re-entered.

## Updates

Updates are command-line based in the first complete version.

Commands:

```text
ai-logctl update
ai-log-agent update
```

Rules:

- Config, reports, memory, and database must survive updates.
- Central update should create a backup or snapshot before changing containers.
- Agent update should keep local config and state.
- Dashboard shows agent versions.
- No silent automatic update in the first version.

## Config Model

Preferred config split:

- `config.yaml` for normal editable product settings.
- `ai.yaml` for AI provider and analysis settings.
- `secrets.env` for secrets.

Files should clearly mark:

- `EDIT`.
- `OPTIONAL`.
- `DO NOT EDIT`.

Runtime-managed state should not be mixed with user-editable config.

## Security and Privacy

Security rules:

- Secrets are never shown in logs or normal UI.
- Enrollment tokens must be validated and protected.
- Redaction runs before AI and before chat notification.
- No remote shell or remote command execution.
- Agent sends logs and metadata only.
- Sensitive config snippets are redacted before storage or analysis.
- Cross-website memory lookup is disabled by default.
- Enrollment tokens can be revoked and rotated.
- Agent credentials can be revoked per machine.
- HTTPS is optional in LAN mode but must be supported for deployments that require encrypted agent-to-server traffic.
- Admin can define custom redaction patterns.

Sensitive patterns:

- Passwords.
- API keys.
- Bearer tokens.
- Private keys.
- Database connection strings with credentials.
- Session cookies.

Token and transport rules:

- Enrollment token is used only to register or re-register an agent.
- After enrollment, the agent should use its own agent credential.
- Token rotation must not require reinstalling every agent.
- Revoking one agent must not affect other agents in the same website.
- HTTP can be allowed for simple trusted LAN deployments.
- HTTPS should be supported with self-signed or customer-provided certificates.

Custom redaction:

- Admin can add patterns for customer-specific secrets.
- Redaction applies before AI input and before chat notifications.
- Raw logs may still contain sensitive data inside the customer's own central server, so access must remain admin-only in the first version.

## Testing and Verification

Core test areas:

- Central installer on Linux + Podman.
- Agent installer and systemd service.
- Agent registration.
- Service/log discovery.
- Permission-safe unreadable log handling.
- Agent offline buffering and resend.
- Server deduplication of retried events.
- Rate limit and backpressure behavior.
- Loss marker creation when bounded buffers overflow.
- Tail offset correctness.
- Timestamp parsing, UTC normalization, and clock skew warnings.
- Multiline log grouping.
- Micro-batch ingestion.
- PostgreSQL metadata storage and raw log segment retention.
- Website isolation by `website_id`.
- Incident grouping.
- Memory creation after resolved incidents.
- AI analysis retry/failure behavior.
- Notification formatting.
- Notification retry/failure state.
- System self-health status.
- Dashboard navigation.
- Backup and restore.
- Update preserving config and state.
- Token revoke/rotate.
- Optional HTTPS agent-to-server traffic.
- Custom redaction rules.

Acceptance examples:

- Install central server, open Dashboard, create a website.
- Generate agent install command and install on a Linux machine.
- Agent discovers relevant known-service and custom application logs without manual log path config.
- Agent buffers events while central server is offline and resends them after recovery.
- Critical pattern triggers immediate analysis.
- Notification is sent once with website, machine, log source, suspected causes, and report link.
- Repeated pattern updates the same incident.
- Resolved incident creates website-scoped memory.
- Similar future incident matches prior memory but verifies current logs before conclusion.

## Open Decisions for Later

These are intentionally outside the first complete version:

- Windows agent.
- Multi-user Dashboard roles.
- Per-website notification routing.
- Full SIEM search/query language.
- SaaS hosting.
- Billing/licensing.
- Remote remediation actions.
- Auto-update from Dashboard.
- Global anonymized knowledge sharing across websites.
