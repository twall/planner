---
name: task
description: Shortcut alias for /planner-task. Add or list planner sessions. Use when user says "/task add ...", "add a session", "remember to...", or asks to see current sessions.
---

# /task — Planner Session Management (alias)

This is an alias for `/planner-task`. See that skill for full documentation.

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
