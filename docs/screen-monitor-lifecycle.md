# ScreenMonitor Lifecycle and Session State

## Self-exclusion

The planner runs inside a screen session (`$STY`). `ScreenBackend.list_sessions` skips
the own session so the planner never monitors itself. Without this, the planner's content
pane shows its own Claude Code output and oscillates ACTIVE/IDLE as Claude processes.

## How the planner attaches to sessions

The planner does not stay running while the user is inside a Claude session. Instead:

1. User selects a task and presses Enter
2. `PlannerApp` calls `_monitor.stop()`, `self.exit(result=attach_cmd)`, saves session states to disk
3. The shell wrapper (`scripts/planner`) runs the attach command (e.g. `screen -d -r <name>`)
4. User works in the Claude session, then detaches
5. Shell wrapper relaunches the planner via `exec "$0"`
6. Planner starts fresh — new `ScreenMonitor` instance, loads cached session states

## Why restart, not stay-alive

- Textual TUI would need to be suspended/restored, which is fragile with screen/tmux
- Exiting and reattaching is cleaner; the shell wrapper handles the loop

## ScreenMonitor skip logic

Sessions proven IDLE get `_skip_until[name] = float("inf")` so they are never re-captured
until woken. This avoids capturing N sessions every poll when only 1 is active.

**Wakeup triggers:**
- `just_detached`: session was Attached last poll, now Detached → always re-captured
- `monitor.wake(name)`: explicit wakeup (e.g. after injecting a prompt)

Do NOT wake on task selection — idle sessions haven't changed, so re-capturing just causes
an ACTIVE→IDLE oscillation as the content diff resolves.

## Restart and skip state

On restart, `_skip_until` is empty. Without restoration, ALL sessions get re-captured on
the first eager poll and may briefly show ACTIVE (no Claude footer on non-Claude sessions,
or content recently changed).

**Fix**: `ScreenMonitor.__init__` restores `_skip_until=inf` for sessions cached as IDLE.

**Problem**: the session the user was just using (attached to, then detached from) is likely
IDLE in the cache (it was idle when the planner last saw it). We must NOT skip it.

**Fix**: `_startup_inner` reads `load_state()` to find the previously-selected task's
screen session and calls `monitor.wake()` on it before the eager `_poll()`.

## Content pane staleness on session switch

When the user navigates to a different task, `on_task_panel_task_selected` fires. It reads
the cached session state from `_monitor.get_sessions()`. If that session was IDLE-skipped,
its `last_lines` may be stale (from before the planner exited).

**Fix**: `on_task_panel_task_selected` calls `monitor.wake()` so the next poll re-captures
the session and `_refresh_sessions` updates the content pane.

## detect_state logic

`detect_state(lines, idle_seconds, attached, idle_threshold, prev_state)`:
- `attached=True` → "ATTACHED" (unconditional)
- PERMISSION_PATTERNS match → "NEEDS PERMISSION"
- PROMPT_PATTERNS match in recent lines → "NEEDS INPUT"
- `idle_seconds >= idle_threshold` → "IDLE"
- Claude footer (`for shortcuts`/`for agents`) present but NOT `esc to interrupt` → "IDLE"
- Otherwise → "ACTIVE"

The Claude footer check avoids false ACTIVE after a turn finishes or on fresh restart,
where a one-time content diff would keep sessions ACTIVE for up to `idle_threshold` seconds.

`_CLAUDE_FOOTER_RE` must match ALL Claude Code idle-footer variants:
- `? for shortcuts` — normal idle at prompt
- `for agents` — multi-agent mode idle
- `manual mode` — manual mode (`⏸ manual mode on`), may appear without shortcuts/agents suffix
- `accept edits` — auto-accept mode (`⏵⏵ accept edits on`), idle when no `esc to interrupt`

Omitting any variant causes those sessions to stay ACTIVE indefinitely instead of going IDLE.
