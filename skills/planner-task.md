---
name: planner-task
description: Add or list tasks in the planner dashboard from any Claude Code session. Use when user says "/planner-task add ...", "/task add ...", "add a task", "remember to...", or asks to see current tasks.
---

# /planner-task — Planner Task Management

Add tasks to the planner dashboard or list current tasks. Alias: `/task`.

## Usage

```
/planner-task add "title" [--today|--week|--backlog] [--priority 1-5]
/planner-task list
```

## Implementation

```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate"
cd "$PLANNER_DIR"
python -m planner.cli add "<title>" [--today|--week|--backlog] [--priority N]
```

For list:
```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli list
```

## Examples

User: "add a task to review the imap performance"
→ `python -m planner.cli add "Review imap graph performance" --week --priority 3`

User: "remind me to check the sentry alerts today"
→ `python -m planner.cli add "Check Sentry alerts" --today --priority 2`

User: "what's on my list?"
→ `python -m planner.cli list`
