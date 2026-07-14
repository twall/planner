---
name: planner-task
description: Add, list, or update sessions in the planner dashboard from any Claude Code session. Use when user says "/planner-task add ...", "/task add ...", "add a session", "remember to...", "update session", "change priority", or asks to see current sessions.
---

# /planner-task — Planner Session Management

Add, list, or update sessions in the planner dashboard. Alias: `/task`.

## Usage

```
/planner-task add "title" [--today|--week|--backlog] [--priority 1-5]
/planner-task list [-v|--verbose]
/planner-task get <id>
/planner-task update <id> [--today|--week|--backlog] [--priority N] [--title "..."] [--desc "..."]
```

## Implementation

```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate"
cd "$PLANNER_DIR"
```

Add:
```bash
python -m planner.cli add "<title>" [--today|--week|--backlog] [--priority N]
```

List:
```bash
python -m planner.cli list           # compact: id, title, horizon, priority
python -m planner.cli list --verbose # also shows description, cwd, session
```

Get full session details as JSON:
```bash
python -m planner.cli get <id>
```

Update (use the id from `list`):
```bash
python -m planner.cli update <id> [--today|--week|--backlog] [--priority N] [--title "new title"] [--desc "new description"]
```

## When to use update

- User asks to reprioritize a session → `--priority N`
- User asks to move a session to a different horizon → `--today`, `--week`, or `--backlog`
- User asks to rename a session → `--title "new title"`
- User asks to set or change the description/prompt → `--desc "..."`

Always `list` first to get the session id before updating.

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

User: "add a session to review the imap performance"
→ `python -m planner.cli add "Review imap graph performance" --week --priority 3`

User: "remind me to check the sentry alerts today"
→ `python -m planner.cli add "Check Sentry alerts" --today --priority 2`

User: "what's on my list?"
→ `python -m planner.cli list`

User: "move the imap review to today and make it priority 1"
→ list first, then `python -m planner.cli update <id> --today --priority 1`

User: "set the description for session 7 to 'run the benchmark suite'"
→ `python -m planner.cli update 7 --desc "run the benchmark suite"`

## Recurring / Scheduled Sessions

Sessions with `rt_frequency` set are scheduled. Key fields (visible via `get <id>`):
- `rt_frequency`: `"daily"` | `"weekly"` | `"interval"`
- `rt_time`: earliest wall-clock time to run (e.g. `"08:00"`)
- `rt_days`: comma-separated weekdays (e.g. `"mon,tue,wed,thu,fri"`)
- `is_prompt`: if `1`, the `description` is sent as a prompt to the Claude session

Sources that support recurring: `slack`, `git`, `sentry`. The `source` field identifies type.

### How the scheduler runs a session (`scheduler.py` → `session_manager.py`)

`Scheduler.run_task()` calls `run_recurring_via_session()`:

1. If a live screen/tmux session exists for the session and Claude is idle (polls for `>` or `❯`):
   - Sends `\033` (Escape) via `send_raw` to abort buffered input without submitting, then `/clear` via `send_input`
   - Sleeps 1.5s after `/clear` so SessionStart hooks finish rendering before polling for idle
   - Waits for Claude idle again, then sends the prompt
2. Otherwise: launches a new session and sends the prompt

### Known bug: `/clear` + prompt race condition

**Symptom**: Scheduled session appears to run — `/clear` fires and prompt text is injected — but the description is treated as user-typed text rather than executed (skill invocations don't fire, or text lands mid-render).

**Root cause**: `_wait_for_claude_ready` polls for `>` or `❯` in the screen capture. After `/clear`, any active `SessionStart` hook (e.g. caveman mode) immediately outputs text containing `>` or `❯`, causing the poller to return too early. The prompt is then sent while Claude is still rendering the `/clear` output.

**Location**: `planner/session_manager.py`, `run_recurring_via_session()` (~line 209).

**Fix**: Send `\033` (Escape) via `send_raw` to abort buffer without submitting, then `/clear`, then sleep 1.5s before polling for idle. Fixed in `session_manager.py` `run_recurring_via_session()`.
