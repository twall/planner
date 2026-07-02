---
name: planner
description: Launch the planner TUI dashboard. Use when user says "/planner", "open planner", "show planner", or "launch planner".
---

# /planner — Launch Planner Dashboard

Launch the planner TUI in the current terminal.

## Implementation

```bash
"${PLANNER_INSTALL_DIR:-$HOME/planner}/scripts/planner"
```

The planner will take over the terminal. When the user detaches from a session or quits, it relaunches automatically.
