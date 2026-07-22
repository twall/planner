import pytest
from unittest.mock import patch, MagicMock
from planner.screen_monitor import parse_screen_ls, detect_state, PROMPT_PATTERNS


SCREEN_LS_OUTPUT = """There are screens on:
\t67261.agent-core\t(Detached)
\t37635.webapp\t(Detached)
\t79406.master\t(Attached)
3 Sockets in /Users/twall/.screen."""


def test_parse_screen_ls_count():
    sessions = parse_screen_ls(SCREEN_LS_OUTPUT)
    assert len(sessions) == 3


def test_parse_screen_ls_fields():
    sessions = parse_screen_ls(SCREEN_LS_OUTPUT)
    agent = next(s for s in sessions if s["name"] == "agent-core")
    assert agent["pid"] == "67261"
    assert agent["attached"] is False
    assert agent["full_name"] == "67261.agent-core"


def test_parse_screen_ls_attached():
    sessions = parse_screen_ls(SCREEN_LS_OUTPUT)
    master = next(s for s in sessions if s["name"] == "master")
    assert master["attached"] is True


def test_detect_state_needs_input():
    lines = ["some output", "Continue? [Y/n]", ""]
    assert detect_state(lines, idle_seconds=0) == "NEEDS INPUT"


def test_detect_state_do_you_want_to():
    lines = ["some output", "Do you want to proceed?", ""]
    assert detect_state(lines, idle_seconds=0) == "NEEDS PERMISSION"


def test_detect_state_allow_deny():
    lines = ["Tool: bash", "Allow this action? (Yes/No)", ""]
    assert detect_state(lines, idle_seconds=0) == "NEEDS PERMISSION"


def test_detect_state_idle():
    lines = ["some output", "some more output"]
    assert detect_state(lines, idle_seconds=35) == "IDLE"


def test_detect_state_active():
    lines = ["some output", "some more output"]
    assert detect_state(lines, idle_seconds=10) == "ACTIVE"


def test_detect_state_attached():
    lines = ["some output"]
    assert detect_state(lines, idle_seconds=0, attached=True) == "ATTACHED"


CLAUDE_IDLE_FOOTER = "  ⏸ manual mode on · ? for shortcuts · ← for agents"
CLAUDE_ACTIVE_FOOTER = "  ⏸ manual mode on · esc to interrupt · ← for agents"


def test_detect_state_claude_idle_footer_returns_idle_at_zero():
    # Claude session at idle prompt: footer has "? for shortcuts", not "esc to interrupt"
    # Should return IDLE even when idle_seconds < threshold (avoids false-ACTIVE on restart)
    lines = ["❯ some prior command", "⏺ result", "❯\xa0", "──────", CLAUDE_IDLE_FOOTER]
    assert detect_state(lines, idle_seconds=0) == "IDLE"


def test_detect_state_claude_active_footer_returns_active():
    # Claude session mid-turn: footer has "esc to interrupt"
    lines = ["✻ Working… (5s · ↓ 123 tokens)", "──────", "❯\xa0", "──────", CLAUDE_ACTIVE_FOOTER]
    assert detect_state(lines, idle_seconds=0) == "ACTIVE"


def test_detect_state_non_claude_session_still_active_on_content_change():
    # Non-Claude terminal (no Claude footer): content change = ACTIVE
    lines = ["$ some bash output", "result here"]
    assert detect_state(lines, idle_seconds=5) == "ACTIVE"
