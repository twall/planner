---
name: planner
description: Launch the planner TUI dashboard, or return to it from within a screen/tmux session. Use when user says "/planner", "open planner", "show planner", or "launch planner".
---

# /planner — Launch or Return to Planner Dashboard

## Step 1: Check environment

Run this to determine the current context:

```bash
echo "STY=${STY:-} TMUX=${TMUX:-} SESSION_ID=${CLAUDE_CODE_SESSION_ID:-}"
```

## Step 2: Act based on context

### Already inside a screen session (`STY` is set)

Detach from screen to return to planner:

```bash
screen -d
```

Tell the user: "Detached from screen session — you should be back in the planner."

### Already inside tmux (`TMUX` is set)

Detach from tmux pane:

```bash
tmux detach-client
```

Tell the user: "Detached from tmux — you should be back in the planner."

### Plain terminal (neither `STY` nor `TMUX` set)

Need to wrap this Claude session into screen so planner can track it, then launch planner.

Determine a session name from the current directory:

```bash
basename "$(pwd)" | tr '[:upper:] ' '[:lower:]-' | sed 's/[^a-z0-9-]//g'
```

Then tell the user to run this command (substitute `SESSION_ID` and `SESSION_NAME`):

```
! PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}" && screen -S "planner-SESSION_NAME-SESSION_ID_SHORT" -dm bash -c "exec claude --resume SESSION_ID" && "$PLANNER_DIR/scripts/planner"
```

Where:
- `SESSION_ID` = value of `$CLAUDE_CODE_SESSION_ID`  
- `SESSION_ID_SHORT` = first 8 chars of session ID
- `SESSION_NAME` = slugified basename of current working directory

**Explain to the user:** "This moves your Claude session into a screen session so planner can monitor it, then launches planner. Run the command above with `!` to execute it in your terminal."

### Planner already running check

If the user says planner is already running but they're not in screen/tmux, tell them:
"Planner is running in your other terminal. Switch to it, or run `/planner` there to relaunch."
