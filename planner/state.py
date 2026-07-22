"""Lightweight UI state persistence (selected task, session states, etc.)."""
import json
from pathlib import Path
from planner.config import STATE_PATH

SESSION_STATE_PATH = STATE_PATH.parent / "session_states.json"


def save_state(selected_task_id: int | None) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        STATE_PATH.write_text(json.dumps({"selected_task_id": selected_task_id}))
    except Exception:
        pass


def load_state() -> dict:
    try:
        return json.loads(STATE_PATH.read_text())
    except Exception:
        return {}


def save_session_states(sessions: list) -> None:
    """Persist session states to disk. sessions is a list of SessionState."""
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = {s.full_name: s.state for s in sessions}
        SESSION_STATE_PATH.write_text(json.dumps(data))
    except Exception:
        pass


def load_session_states() -> dict[str, str]:
    """Load cached session states. Returns {full_name: state}. Deletes file after read."""
    try:
        data = json.loads(SESSION_STATE_PATH.read_text())
        SESSION_STATE_PATH.unlink(missing_ok=True)
        return data
    except Exception:
        return {}
