---
name: planner-add
description: Add one or more tasks to the planner inbox. Use when user says "/planner-add", "add to planner", "make planner tasks for these", "create planner tasks", or when you have a list of action items that should become planner tasks. Tasks are picked up next time the planner launches or restarts.
---

# /planner-add — Add Tasks to Planner

Queue one or more tasks for the planner. Tasks appear when the planner next starts (or restarts after a session detach).

## Implementation

```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate"
cd "$PLANNER_DIR"
python -m planner.cli inbox add "<title>" [--desc "<description>"] [--today|--week|--backlog]
```

Default horizon is `--week` if not specified.

## Examples

User: "make planner tasks for these sentry issues"
→ For each item in the list:
```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli inbox add "Fix null pointer in auth middleware" --desc "Sentry WEBAPP-123: NullPointerException at auth/middleware.py:45" --week
python -m planner.cli inbox add "Review rate limiting gaps" --week
```

User: "add to planner: review the imap PR"
```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli inbox add "Review imap PR" --week
```

## Output

After adding all tasks, confirm:
```
Queued N tasks for planner:
  • Fix null pointer in auth middleware [this_week]
  • Review rate limiting gaps [this_week]
```

Tasks will appear in the planner the next time it launches.
