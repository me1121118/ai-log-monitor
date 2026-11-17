# Hide Empty Websites From Overview

## Goal

Keep the Overview focused on websites that have at least one registered agent. A manually created or historical website with zero registered agents must not appear as a card.

## Approved Behavior

- Hide a website when its total registered agent count is zero (`0/0`).
- Keep a website visible when registered agents exist, even if all of them are offline (`0/N`).
- Show a website automatically after its first agent registers.
- Hide it automatically after all agents are reassigned away or removed in a future agent-management flow.
- Preserve website metadata, events, incidents, raw logs, and AI incident memory.
- Do not add a delete button or destructive API.

## Architecture

The database remains the source of truth and is not modified by this feature. The dashboard rendering layer will build the set of visible websites by joining registered websites with the current agent list and retaining only website IDs referenced by at least one agent.

Filtering belongs in the Overview presentation path so existing APIs, website-specific history, analysis, retention, and incident correlation remain unchanged.

## Data Flow

1. Load registered websites.
2. Load agents and their health state.
3. Build the set of website IDs present in the agent list.
4. Render Overview cards only for websites in that set.
5. Determine Online or Offline from agent health exactly as today.

## Empty State

When no website has a registered agent, show the existing empty dashboard state instead of an empty grid or stale summary counters.

## Error Handling

If agent loading fails, the dashboard health path should report the existing degraded state. The renderer must not delete or mutate website records as a fallback.

## Tests

- A registered website with zero agents is absent from Overview HTML.
- A website with one active agent is present and Online.
- A website with registered but stale agents is present and Offline.
- Hidden websites retain events and incidents in storage.
- Existing website APIs continue to list stored website records.

## Out of Scope

- Permanent website deletion.
- Automatic deletion of agents, events, incidents, raw logs, or AI memory.
- Retention-policy changes.
- Notification-system changes.
