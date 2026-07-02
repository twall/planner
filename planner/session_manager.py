import time
import uuid
from pathlib import Path

from planner.backends import get_backend
from planner.db import add_task, list_tasks, update_task

SESSION_NAME_PREFIX = "planner"


def session_name_for(task_id: int) -> str:
    return f"{SESSION_NAME_PREFIX}-{task_id}"


def _live_sessions() -> dict[str, dict]:
    backend = get_backend()
    try:
        sessions = backend.list_sessions()
        return {s.full_name: {"name": s.name, "full_name": s.full_name,
                              "attached": s.attached} for s in sessions}
    except Exception:
        return {}


def launch_session(db_path: Path, task: dict, cwd: str | None = None,
                   cols: int = 220, rows: int = 50) -> str:
    """Launch a multiplexer session + claude for task. Returns session full_name."""
    backend = get_backend()
    task_id = task["id"]
    name = session_name_for(task_id)
    session_id = str(uuid.uuid4())
    shell_cmd = f"exec claude --session-id {session_id}"
    backend.launch(name, shell_cmd, cwd=cwd, cols=cols, rows=rows)
    # full_name differs by backend: screen uses PID.name, tmux uses name
    # Resolve by looking up the just-created session
    full_name = _resolve_full_name(backend, name) or name
    update_task(db_path, task_id, screen_session=full_name, claude_session_id=session_id)
    if task.get("description"):
        time.sleep(2)
        backend.send_input(full_name, task["description"])
    return full_name


def _resolve_full_name(backend, name: str) -> str | None:
    """Find the full_name for a session by its short name (needed for screen's PID.name format)."""
    try:
        for s in backend.list_sessions():
            if s.name == name:
                return s.full_name
    except Exception:
        pass
    return None


def resume_sessions(db_path: Path) -> int:
    """Recreate sessions for tasks with claude_session_id but no live session."""
    backend = get_backend()
    live = _live_sessions()
    live_names = {s["name"] for s in live.values()}
    tasks = list_tasks(db_path)
    resumed = 0
    for t in tasks:
        if not t.get("claude_session_id"):
            continue
        name = session_name_for(t["id"])
        if name in live_names:
            continue
        shell_cmd = f"exec claude --resume {t['claude_session_id']}"
        backend.launch(name, shell_cmd)
        full_name = _resolve_full_name(backend, name) or name
        update_task(db_path, t["id"], screen_session=full_name)
        resumed += 1
    return resumed


def kill_session(screen_session: str) -> None:
    get_backend().kill(screen_session)


def send_input(screen_session: str, text: str) -> None:
    get_backend().send_input(screen_session, text)


def import_orphan_sessions(db_path: Path) -> int:
    """Import multiplexer sessions not linked to any task. Returns count added."""
    live = _live_sessions()
    tasks = list_tasks(db_path)
    linked_names = set()
    for t in tasks:
        if t.get("screen_session"):
            linked_names.add(t["screen_session"])
            if "." in t["screen_session"]:
                linked_names.add(t["screen_session"].split(".", 1)[1])

    imported = 0
    for full_name, s in live.items():
        if s["name"] in linked_names or full_name in linked_names:
            continue
        add_task(db_path, source="screen", title=s["name"],
                 screen_session=full_name, horizon="this_week")
        imported += 1
    return imported


def run_recurring_via_session(db_path: Path, task_dict: dict, prompt: str) -> None:
    """Run recurring task: reuse live session (/clear + prompt) or launch new."""
    backend = get_backend()
    if task_dict.get("screen_session") and task_dict.get("claude_session_id"):
        live = _live_sessions()
        name = task_dict["screen_session"]
        if any(s["name"] == name or s["full_name"] == name for s in live.values()):
            backend.send_input(name, "/clear")
            time.sleep(1)
            backend.send_input(name, prompt)
            return
    launch_session(db_path, task_dict)
    time.sleep(2)
    backend.send_input(session_name_for(task_dict["id"]), prompt)
