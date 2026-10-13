"""Lightweight UI state persistence (selected task, session states, etc.)."""
import json
import time
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
    """Persist session states to disk. sessions is a list of SessionState.

    Stores a wall-clock "went idle at" timestamp (derived from idle_seconds)
    so a restart can reconstruct how long a session has actually been idle,
    instead of treating every cached session as freshly finished.
    """
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        now = time.time()
        data = {s.full_name: {"state": s.state, "lines": s.last_lines,
                               "ts": now - s.idle_seconds}
                for s in sessions}
        SESSION_STATE_PATH.write_text(json.dumps(data))
    except Exception:
        pass


def load_session_states() -> dict[str, dict]:
    """Load cached session states. Returns {full_name: {state, lines, ts}}. Deletes file after read."""
    try:
        raw = json.loads(SESSION_STATE_PATH.read_text())
        SESSION_STATE_PATH.unlink(missing_ok=True)
        result = {}
        for k, v in raw.items():
            entry = v if isinstance(v, dict) else {"state": v, "lines": []}
            # Support old format / missing ts; treat as unknown/stale rather
            # than just-finished, so it doesn't falsely show as fresh.
            entry.setdefault("ts", 0)
            result[k] = entry
        return result
    except Exception:
        return {}
