---
name: planner-organize
description: Analyze and organize planner tasks into suggested categories, or reprioritize them. Use when user says "/planner-organize", "organize my tasks", "categorize tasks", "what should I work on", "reprioritize", or asks for a task overview or suggestions.
---

# /planner-organize — Organize and Prioritize Planner Tasks

Read current tasks, analyze them, and propose groupings and priority changes. Present suggestions to the user before applying anything.

## Step 1: Read current tasks

```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli list
```

## Step 2: Analyze and propose

Group tasks into **3–5 categories** based on their titles, sources, and current horizons. Consider:
- Active sessions (screen/tmux) vs no session
- Source type: jira, sentry, bitbucket, slack, freeform, builtin
- Apparent theme: infrastructure, product, tooling, monitoring, backlog cleanup
- Current horizon: today vs this_week vs backlog

Present the proposed groupings and any priority/horizon changes in a clear summary. Example format:

```
Proposed organization:

GROUP 1 — Active Work (move to this_week)
  • agent-core [active session]
  • webapp [active session]
  • api-cleanup [active session]

GROUP 2 — Monitoring / Ops (keep today, p2)
  • Slack Digest
  • Sentry Gap Check
  • Bitbucket PR Review

GROUP 3 — Product Features (backlog, p3)
  • imap
  • vector-prompt
  • parallel-tools

GROUP 4 — Releases (backlog, p2)
  • 9.1.x
  • 10.0.x

GROUP 5 — Defer / Low priority (backlog, p4)
  • spit-compounds
  • cigs

Changes proposed:
  - Move agent-core, webapp, api-cleanup → this_week
  - Set 9.1.x, 10.0.x → p2
  - Set spit-compounds, cigs → p4

Apply these changes? (yes / edit / skip)
```

## Step 3: Apply if confirmed

Only apply after explicit user confirmation. For each change:

```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli update <id> [--today|--week|--backlog] [--priority N]
```

Multiple updates in one shot:
```bash
for change in "3 --week --priority 2" "7 --backlog --priority 4" "14 --week"; do
  python -m planner.cli update $change
done
```

After applying, confirm:
```
Applied N changes. Changes take effect next time planner refreshes (within ~5s).
```

## Notes

- Never delete tasks or mark done without explicit instruction
- Locked sources (jira, sentry, bitbucket, slack, builtin) can have horizon/priority changed but titles are fixed
- If user asks to "just show" without applying, stop at Step 2
- If user says "reprioritize" without "organize", focus on priority numbers rather than groupings
- If user says "what should I work on today", suggest 2–3 specific tasks with brief reasoning
