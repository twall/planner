---
name: planner-add
description: Add one or more sessions to the planner inbox. Use when user says "/planner-add", "add to planner", "make planner sessions for these", "create planner sessions", or when you have a list of action items that should become planner sessions. Sessions are picked up next time the planner launches or restarts.
---

# /planner-add — Add Sessions to Planner

Queue one or more sessions for the planner. Sessions appear when the planner next starts (or restarts after a session detach).

## Implementation

```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate"
cd "$PLANNER_DIR"
python -m planner.cli inbox add "<title>" [--desc "<description>"] [--today|--week|--backlog]
```

Default horizon is `--week` if not specified.

## Title and description format

When a session references a Sentry or JIRA issue:

**Title** — prefix with the issue ID:
- Sentry: `WEBAPP-JR: Fix null pointer in auth middleware`
- JIRA: `PLEX-1234: Review rate limiting gaps`

**Description (prompt)** — MUST include the ticket reference so the claude session knows where to look. Build it from:
1. The ticket ID/URL as the first line
2. Any known context (error message, stack trace snippet, issue summary)
3. A clear action directive

Templates:

Sentry issue:
```
Fix Sentry issue WEBAPP-JR (https://sentry.plexsearch.com/organizations/plex/issues/WEBAPP-JR/).
<one-line summary of the error>
<stack trace snippet or key detail if available>
```

JIRA issue:
```
Work on JIRA ticket PLEX-1234 (https://plexresearch.atlassian.net/browse/PLEX-1234).
<summary from the ticket>
<acceptance criteria or key detail if available>
```

If you don't have the URL, use just the key — claude can look it up via MCP tools.

## Examples

User: "make planner sessions for these sentry issues"
→ For each item in the list:
```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli inbox add "WEBAPP-123: Fix null pointer in auth middleware" \
  --desc "Fix Sentry issue WEBAPP-123 (https://sentry.plexsearch.com/organizations/plex/issues/WEBAPP-123/).
NullPointerException at auth/middleware.py:45 — token is None when refresh races with expiry." --week
python -m planner.cli inbox add "PLEX-456: Review rate limiting gaps" \
  --desc "Work on JIRA ticket PLEX-456 (https://plexresearch.atlassian.net/browse/PLEX-456).
Audit rate limiting coverage across REST API endpoints and propose fixes." --week
```

User: "add to planner: review the imap PR"
```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli inbox add "Review imap PR" --week
```

## Output

After adding all sessions, confirm:
```
Queued N sessions for planner:
  • Fix null pointer in auth middleware [this_week]
  • Review rate limiting gaps [this_week]
```

Sessions will appear in the planner the next time it launches.
