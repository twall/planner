---
name: planner-task
description: Add, list, or update tasks in the planner dashboard from any Claude Code session. Use when user says "/planner-task add ...", "/task add ...", "add a task", "remember to...", "update task", "change priority", or asks to see current tasks.
---

# /planner-task — Planner Task Management

Add, list, or update tasks in the planner dashboard. Alias: `/task`.

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

Get full task details as JSON:
```bash
python -m planner.cli get <id>
```

Update (use the id from `list`):
```bash
python -m planner.cli update <id> [--today|--week|--backlog] [--priority N] [--title "new title"] [--desc "new description"]
```

## When to use update

- User asks to reprioritize a task → `--priority N`
- User asks to move a task to a different horizon → `--today`, `--week`, or `--backlog`
- User asks to rename a task → `--title "new title"`
- User asks to set or change the description/prompt → `--desc "..."`

Always `list` first to get the task id before updating.

## Title and description format

When a task references a Sentry or JIRA issue:

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

User: "add a task to review the imap performance"
→ `python -m planner.cli add "Review imap graph performance" --week --priority 3`

User: "remind me to check the sentry alerts today"
→ `python -m planner.cli add "Check Sentry alerts" --today --priority 2`

User: "what's on my list?"
→ `python -m planner.cli list`

User: "move the imap review to today and make it priority 1"
→ list first, then `python -m planner.cli update <id> --today --priority 1`

User: "set the description for task 7 to 'run the benchmark suite'"
→ `python -m planner.cli update 7 --desc "run the benchmark suite"`
