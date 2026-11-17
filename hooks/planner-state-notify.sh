#!/usr/bin/env bash
# Claude Code hook: notify planner of session state changes.
#
# Handles: Stop, PreToolUse, Notification, SessionEnd events.
# Writes ~/.planner/hook_states/<session_id>.json so planner's screen_monitor
# can show accurate state without heuristic screen-capture parsing.
#
# Installed by planner itself (planner/app.py:_install_hooks) into
# ~/.claude/hooks/ and wired into ~/.claude/settings.json on every startup —
# do not hand-edit the installed copy, edit this source and restart planner.
#
# Hook input (stdin): {"hook_event_name": "...", "session_id": "...", ...}

set -euo pipefail

PLANNER_ROOT="${PLANNER_INSTALL_DIR:-$HOME/planner}"
PLANNER_PY="$PLANNER_ROOT/.venv/bin/python3"

INPUT=$(cat)
EVENT=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('hook_event_name',''))" 2>/dev/null || echo "")
SESSION_ID=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('session_id',''))" 2>/dev/null || echo "")

[ -z "$SESSION_ID" ] && exit 0

# SessionEnd means the claude process is actually exiting — this is the only
# point where the task<->session DB link should be severed. Stop fires at the
# end of every turn (not process exit), so clearing here previously nuked the
# link mid-conversation on every turn, breaking planner's message delivery
# and causing duplicate session launches for still-running tasks.
#
# Only sever the link for reasons that mean the conversation itself is gone
# (clear, logout). Reasons like "other"/"prompt_input_exit" mean the user
# just quit the process — the task<->session link must survive so the next
# launch resumes the same conversation instead of starting a fresh one.
if [ "$EVENT" = "SessionEnd" ]; then
    REASON=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('reason',''))" 2>/dev/null || echo "")
    case "$REASON" in
        clear|logout)
            "$PLANNER_PY" -m planner.cli clear-session --session-id "$SESSION_ID" 2>/dev/null || true
            ;;
    esac
    exit 0
fi

case "$EVENT" in
    Stop)
        STATE="idle"
        ;;
    PreToolUse)
        STATE="active"
        ;;
    Notification)
        # Notification fires for permission requests, but also for Claude Code's
        # routine "Claude is waiting for your input" idle ping — sent whenever a
        # turn ends and the terminal is unfocused, same moment as a Stop event.
        # That ping isn't a blocking question (those show up as an actual on-screen
        # prompt, caught by screen_monitor's own pattern scan) so it must not be
        # escalated to needs-input — doing so previously got stuck "NEEDS INPUT"
        # forever once it raced after Stop's "idle" write, since needs-input has
        # no expiry (unlike the 30s one for "active").
        TITLE=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('title',''))" 2>/dev/null || echo "")
        MESSAGE=$(echo "$INPUT" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('message',''))" 2>/dev/null || echo "")
        COMBINED="${TITLE} ${MESSAGE}"
        if echo "$COMBINED" | grep -qi "permission\|allow\|approve\|trust"; then
            STATE="needs-permission"
        elif echo "$COMBINED" | grep -qi "waiting for your input"; then
            STATE="idle"
        else
            # Unrecognized notification text — don't guess, leave existing state alone.
            exit 0
        fi
        ;;
    *)
        exit 0
        ;;
esac

SCREEN_SESSION_ARG=""
[ -n "${STY:-}" ] && SCREEN_SESSION_ARG="--screen-session $STY"
"$PLANNER_PY" -m planner.cli notify --session-id "$SESSION_ID" --state "$STATE" $SCREEN_SESSION_ARG 2>/dev/null || true
