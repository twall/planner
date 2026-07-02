"""Lightweight UI state persistence (selected task, etc.)."""
import json
from planner.config import STATE_PATH


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
