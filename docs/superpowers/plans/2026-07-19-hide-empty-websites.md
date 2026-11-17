# Hide Empty Websites Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hide `0/0` websites from Overview while keeping websites with registered offline agents visible.

**Architecture:** Add a presentation-only filter in `server/app/ui.py`. The filter derives visible Overview websites from the registered agent list and does not mutate website, event, incident, raw-log, or AI-memory storage.

**Tech Stack:** Python 3.13, standard-library `unittest`, server-rendered HTML.

## Global Constraints

- Hide a website only when its total registered agent count is zero (`0/0`).
- Keep a website visible when registered agents exist, even if all are offline (`0/N`).
- Preserve all stored data and existing management APIs.
- Do not add a delete endpoint or database migration.
- `C:\ai_server_log` is not a Git repository; use timestamped production backups for rollback instead of a local commit.

---

### Task 1: Filter Empty Websites From Overview

**Files:**
- Modify: `C:\ai_server_log\server\tests\test_dashboard_admin.py`
- Modify: `C:\ai_server_log\server\server\app\ui.py`

**Interfaces:**
- Consumes: `websites: list[dict[str, Any]]` and `agents: list[dict[str, Any]]` already passed to `_render_dashboard`.
- Produces: `_overview_websites(websites, agents) -> list[dict[str, Any]]`, preserving website order.

- [x] **Step 1: Write failing behavior tests**

Add tests to `DashboardAdminTests` that create an empty website and assert it is absent from Overview while still returned by `/api/websites`, then register an offline agent and assert that website remains visible as Offline.

```python
def test_overview_hides_zero_agent_website_without_deleting_it(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(Path(temp_dir))
        app.handle_json(
            "POST",
            "/api/websites",
            {},
            json.dumps({"website_id": "unused_site", "name": "Unused Site"}).encode("utf-8"),
        )

        html = app.dashboard_html().decode("utf-8")
        _status, _headers, body = app.handle_json("GET", "/api/websites", {}, b"")

        self.assertIn('class="empty-dashboard"', html)
        self.assertNotIn("unused_site", html)
        self.assertEqual(json.loads(body.decode("utf-8"))["websites"][0]["website_id"], "unused_site")

def test_overview_keeps_website_with_registered_offline_agent(self):
    with tempfile.TemporaryDirectory() as temp_dir:
        app = create_app(Path(temp_dir))
        app.handle_json(
            "POST",
            "/api/agents/register",
            {"X-Enroll-Token": "change-this-install-token"},
            json.dumps({"agent_id": "db01", "agent_role": "db", "website_id": "website_1"}).encode("utf-8"),
        )
        app.store.update_agent_heartbeat({
            "agent_id": "db01",
            "status": "offline",
            "observed_at": "2026-07-19T00:00:00+00:00",
        })

        html = app.dashboard_html().decode("utf-8")

        self.assertIn("website_1", html)
        self.assertIn("Offline", html)
        self.assertIn("0/1", html)
```

- [x] **Step 2: Run the focused tests and verify RED**

Run:

```powershell
python -m unittest tests.test_dashboard_admin.DashboardAdminTests.test_overview_hides_zero_agent_website_without_deleting_it tests.test_dashboard_admin.DashboardAdminTests.test_overview_keeps_website_with_registered_offline_agent
```

Expected: the first test fails because `unused_site` is rendered and the existing empty dashboard is not returned.

- [x] **Step 3: Implement the presentation filter**

Add this helper to `server/app/ui.py`:

```python
def _overview_websites(
    websites: list[dict[str, Any]],
    agents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    agent_website_ids = {
        str(agent.get("website_id") or "").strip()
        for agent in agents
        if str(agent.get("website_id") or "").strip()
    }
    return [website for website in websites if str(website.get("website_id") or "") in agent_website_ids]
```

In `_render_dashboard`, derive `overview_websites` after `selected_page`, return `_render_empty_dashboard()` when the Overview has none, and pass `overview_websites` to `_render_mockup_overview`. Do not replace `websites` for other pages.

- [x] **Step 4: Verify GREEN and regression coverage**

Run the focused tests again, then:

```powershell
python -m unittest discover -s tests -p "test_*.py"
```

Expected: focused tests pass. All non-installer tests pass; `test_server_installer.py` may retain the known local WSL/bash timeout and must be reported separately rather than treated as this feature's regression.

- [x] **Step 5: Deploy and verify production behavior**

Back up the current production `ui.py`, upload the tested file, rebuild `localhost/ai-log-server-v2:latest`, and recreate `ai-log-server` with the existing environment and `/home/kdtadmin/ai_server_log_v2/server/data-prod:/data` mount.

Verify:

```text
GET /health returns {"status":"ok"}
Overview omits web_1 (0/0)
Overview keeps website_1 because db1/db2/web1 remain registered
GET /api/websites still contains the stored web_1 record
```
