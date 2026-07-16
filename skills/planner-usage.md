---
name: planner-usage
description: Reference for how the planner works — concepts, keybindings, task lifecycle, horizons, session states, sources, and troubleshooting. Use when user asks "how does X work in planner", "what does this_week mean", "why won't my session connect", "what keys do what", or any planner how/why question that isn't an add/update/list operation.
---

# Planner — Usage Reference

## Concepts

### Horizons

Tasks live in one of three horizons, shown as groups in the TUI:

| Horizon | Meaning |
|---------|---------|
| `today` | On today's active list — promoted on planner launch |
| `this_week` | Week bucket — defer for later in the week |
| `backlog` | Long-term / someday |

`m` in the TUI cycles a task through horizons: `today → this_week → backlog → today`.

On launch, if a task with an active screen/tmux session is in `this_week`, it is **auto-promoted to `today`**.

### Sources

| Source | Origin | Notes |
|--------|--------|-------|
| `claude` | Claude Code (via `/planner-add` or `/planner-task`) | Free-form tasks from Claude sessions |
| `screen` / `tmux` | Orphan sessions imported from the multiplexer | Sessions found running without a linked task |
| `jira` | JIRA sync | Managed externally; title locked |
| `sentry` | Sentry issues | Managed externally; title locked |
| `bitbucket` | PR review tasks | Managed externally; title locked |
| `slack` | Slack digest | Recurring; managed |
| `git` | Git activity digests | Recurring; managed |
| `builtin` | Built-in recurring tasks (Slack Digest, Sentry Gap Check, etc.) | System tasks |

Externally-managed sources (jira, sentry, bitbucket, slack, builtin) can have horizon/priority changed but titles are fixed.

### Session States

Each task can have a linked screen/tmux session. The right pane shows the session state:

| State | Meaning |
|-------|---------|
| `IDLE` | Claude is at the prompt — ready for input |
| `BUSY` | Claude is processing |
| `STOPPED` | Session exists but Claude exited |
| No session | Task has never been started, or session was killed |

The planner polls sessions every ~3s. State badges update automatically.

### Task lifecycle

1. Task created (via TUI `n`, `/planner-add`, `/planner-task add`, or sync)
2. Task selected + `Enter` → planner launches a screen/tmux session running `claude --session-id <uuid>`
3. Session linked: `screen_session` and `claude_session_id` stored in DB
4. Attach: planner exits, terminal drops into the screen session
5. Detach (`Ctrl+A D` for screen, `Ctrl+B D` for tmux): returns to planner
6. Task marked done: `d` in TUI kills session and marks `status=done`

If the session crashes or is killed externally, the task shows `STOPPED`. `Enter` on it opens a **resume prompt** — planner runs `claude --resume <session_id>` to restore conversation history.

---

## Keybindings (TUI)

| Key | Action |
|-----|--------|
| `↑` / `↓` / `J` / `K` | Move task cursor |
| `Enter` | Content pane: attach to session (or start/resume). Task pane: edit task |
| `←` / `→` | Switch between content pane and task pane |
| `p` | Preview session output fullscreen |
| `n` | New task |
| `d` | Delete task (kills session if any) |
| `m` | Cycle horizon: today → this_week → backlog → today |
| `Ctrl+S` | Start Claude session for task |
| `j` | Sync JIRA |
| `b` | Re-run PR review (bitbucket tasks) |
| `s` | Re-run Slack digest |
| `R` | Re-run all recurring tasks |
| `h` / `?` | Show keybinding help overlay |
| `q` | Quit planner |

---

## CLI (from any terminal)

```bash
PLANNER_DIR="${PLANNER_INSTALL_DIR:-$HOME/planner}"
source "$PLANNER_DIR/.venv/bin/activate" && cd "$PLANNER_DIR"
python -m planner.cli <command>
```

| Command | Effect |
|---------|--------|
| `list` | List all open tasks (compact) |
| `list --verbose` | Include description, cwd, session |
| `get <id>` | Full task JSON |
| `add "title" [--today\|--week\|--backlog] [--priority N]` | Add task directly to DB |
| `inbox add "title" [--desc "..."] [--today\|--week\|--backlog]` | Queue for next planner launch |
| `update <id> [--today\|--week\|--backlog] [--priority N] [--title "..."] [--desc "..."]` | Update task |

---

## Troubleshooting

### Session flashes and returns to planner

`claude --resume <session_id>` failed — session ID is stale (no backing `.jsonl` in `~/.claude/projects/`). Fix:

```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/planner')
from planner.db import update_task
from planner.config import DB_PATH
update_task(DB_PATH, <task_id>, claude_session_id=None, screen_session=None)
"
```

Then relaunch — planner starts a fresh session.

### Session shows as dead even though it's running

Screen `full_name` includes PID (`1234.task-17-foo`). After restart the PID changes; old stored `screen_session` no longer matches. Planner tries to resume as if dead. Fixed in `session_manager.py` via `_bare_name()` stripping PID before matching — update to latest if this is recurring.

### Task won't connect (session exists but Enter does nothing)

Check that `screen_session` in DB matches the live session name:

```bash
screen -ls   # or: tmux ls
python -m planner.cli get <id>   # shows screen_session field
```

If mismatched, update:
```bash
python -m planner.cli update <id> --screen-session "<full_name>"
```

Or clear and relaunch to re-link:
```bash
python3 -c "
import sys; sys.path.insert(0, '$HOME/planner')
from planner.db import update_task; from planner.config import DB_PATH
update_task(DB_PATH, <id>, screen_session=None, claude_session_id=None)
"
```

### Recurring task prompt not firing / lands as raw text

Known race: after `/clear`, SessionStart hooks output text containing `>` or `❯`, causing the idle poller to return too early. Fixed in `run_recurring_via_session()` — sends `\033` (Escape) before `/clear`, then sleeps 1.5s before polling. Update to latest if this occurs.

### Planner not picking up inbox tasks

Inbox at `~/.planner/inbox.json` is consumed on planner **startup**. Tasks added via `/planner-add` won't appear until planner restarts or detaches/reattaches.

---

## File locations

| File | Purpose |
|------|---------|
| `~/planner/planner.db` | Tasks database (SQLite) |
| `~/.planner/inbox.json` | Queued tasks (consumed on startup) |
| `~/planner/settings.json` | Integrations config (JIRA projects, Sentry projects, etc.) |
| `~/planner/tasks.json` | Recurring tasks config |
| `~/planner/skills/` | Skill source files (symlinked to `~/.claude/commands/`) |
