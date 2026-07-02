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
