import time
import uuid
from pathlib import Path

from planner.backends import get_backend
from planner.db import add_task, list_tasks, update_task

SESSION_NAME_PREFIX = "planner"


def _slugify(title: str) -> str:
    """Convert task title to a safe session name component."""
    import re
    slug = title.lower().strip()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = slug.strip("-")
    return slug[:40] or "task"


def session_name_for(task_id: int, title: str | None = None) -> str:
    if title:
        return f"{SESSION_NAME_PREFIX}-{_slugify(title)}-{task_id}"
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
    name = session_name_for(task_id, task.get("title"))
    session_id = str(uuid.uuid4())
    shell_cmd = f"exec claude --session-id {session_id}"
    effective_launch_cwd = str(Path(cwd).expanduser()) if cwd else None
    backend.launch(name, shell_cmd, cwd=effective_launch_cwd, cols=cols, rows=rows)
    # full_name differs by backend: screen uses PID.name, tmux uses name
    # Resolve by looking up the just-created session
    full_name = _resolve_full_name(backend, name) or name
    update_kwargs: dict = dict(screen_session=full_name, claude_session_id=session_id)
    if effective_launch_cwd:
        update_kwargs["cwd"] = effective_launch_cwd
    update_task(db_path, task_id, **update_kwargs)
    is_prompt = task.get("is_prompt", 1)
    if is_prompt is None:
        is_prompt = 1
    if task.get("description") and bool(int(is_prompt)):
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
        name = session_name_for(t["id"], t.get("title"))
        if name in live_names:
            continue
        shell_cmd = f"exec claude --resume {t['claude_session_id']}"
        raw = t.get("cwd") or None
        launch_cwd = str(Path(raw).expanduser()) if raw else None
        backend.launch(name, shell_cmd, cwd=launch_cwd)
        full_name = _resolve_full_name(backend, name) or name
        update_task(db_path, t["id"], screen_session=full_name)
        resumed += 1
    return resumed


def resume_session(db_path: Path, task: dict, cwd: str | None = None,
                   cols: int = 220, rows: int = 50) -> str:
    """Resume a dead session using stored claude_session_id. Returns full_name."""
    backend = get_backend()
    task_id = task["id"]
    session_id = task["claude_session_id"]
    raw_cwd = cwd or task.get("cwd") or None
    effective_cwd = str(Path(raw_cwd).expanduser()) if raw_cwd else None
    name = session_name_for(task_id, task.get("title"))
    shell_cmd = f"exec claude --resume {session_id}"
    backend.launch(name, shell_cmd, cwd=effective_cwd, cols=cols, rows=rows)
    full_name = _resolve_full_name(backend, name) or name
    update_kwargs: dict = dict(screen_session=full_name)
    if effective_cwd:
        update_kwargs["cwd"] = effective_cwd
    update_task(db_path, task_id, **update_kwargs)
    return full_name


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

    task_by_id = {t["id"]: t for t in tasks}
    imported = 0
    for full_name, s in live.items():
        if s["name"] in linked_names or full_name in linked_names:
            continue
        # Try to relink a planner-owned session to its task by ID suffix
        relinked = _relink_by_id(db_path, s["name"], full_name, task_by_id)
        if relinked:
            continue
        # Truly orphaned non-planner session — import as new task
        if s["name"].startswith(SESSION_NAME_PREFIX + "-"):
            continue  # planner-owned but unresolvable; skip rather than duplicate
        add_task(db_path, source="screen", title=s["name"],
                 screen_session=full_name, horizon="this_week")
        imported += 1
    return imported


def _relink_by_id(db_path: Path, name: str, full_name: str,
                  task_by_id: dict) -> bool:
    """If session name ends with -{task_id}, relink DB task to this session. Return True if relinked."""
    import re
    m = re.search(r"-(\d+)$", name)
    if not m:
        return False
    task_id = int(m.group(1))
    if task_id not in task_by_id:
        return False
    update_task(db_path, task_id, screen_session=full_name)
    return True


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
    backend.send_input(session_name_for(task_dict["id"], task_dict.get("title")), prompt)
