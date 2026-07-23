import json
import time
import uuid
from pathlib import Path

from planner.backends import get_backend
from planner.config import IGNORED_SESSIONS_PATH
from planner.db import add_task, list_tasks, update_task


def load_ignored_sessions() -> set[str]:
    try:
        return set(json.loads(IGNORED_SESSIONS_PATH.read_text()))
    except Exception:
        return set()


def ignore_session(name: str) -> None:
    ignored = load_ignored_sessions()
    ignored.add(name)
    IGNORED_SESSIONS_PATH.parent.mkdir(parents=True, exist_ok=True)
    IGNORED_SESSIONS_PATH.write_text(json.dumps(sorted(ignored), indent=2))

SESSION_NAME_PREFIX = "task"


def session_name_for(task_id: int, title: str | None = None) -> str:
    if title:
        import re
        slug = re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:30]
        return f"{SESSION_NAME_PREFIX}-{task_id}-{slug}"
    return f"{SESSION_NAME_PREFIX}-{task_id}"


def _live_sessions() -> dict[str, dict]:
    backend = get_backend()
    try:
        sessions = backend.list_sessions()
        return {s.full_name: {"name": s.name, "full_name": s.full_name,
                              "attached": s.attached} for s in sessions}
    except Exception:
        return {}


def _rename_claude_session(backend, full_name: str, title: str, jira_key: str | None = None) -> None:
    """Send /rename <title> to set the Claude session name."""
    safe_title = title.replace("\n", " ").replace("\r", " ").strip()
    # Keep rename short: "PLEX-123 short title" truncated to ~60 chars
    label = f"{jira_key} {safe_title}" if jira_key else safe_title
    label = label[:60].strip()
    backend.send_input(full_name, f"/rename {label}")


def _send_commands(backend, full_name: str, text: str, auto_submit: bool = True) -> None:
    """Populate prompt into the input buffer; submit only if auto_submit=True."""
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    prompt = " ".join(lines)
    _wait_for_claude_ready(backend, full_name)
    if auto_submit:
        backend.send_input(full_name, prompt)
    else:
        backend.send_raw(full_name, prompt)


def _wait_for_claude_ready(backend, full_name: str, timeout: float = 15.0) -> bool:
    """Poll screen capture until claude's idle input prompt (❯) is visible. Returns True if ready."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        lines = backend.capture(full_name)
        # Match only lines where ❯ or > appears as the prompt char (start of a non-indented line)
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("❯") or (stripped.startswith(">") and not stripped.startswith(">>")):
                return True
        time.sleep(0.5)
    return False


def _input_buffer_has_text(backend, full_name: str) -> bool:
    """Return True if the claude input line already has text typed (prompt already populated)."""
    lines = backend.capture(full_name)
    for line in reversed(lines):
        stripped = line.strip()
        if stripped.startswith("❯") or stripped.startswith(">"):
            after_prompt = stripped[1:].strip()
            return bool(after_prompt)
    return False


def launch_session(db_path: Path, task: dict, cwd: str | None = None,
                   cols: int = 220, rows: int = 50,
                   send_prompt: bool = True) -> str:
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
    if task.get("title"):
        _wait_for_claude_ready(backend, full_name)
        _rename_claude_session(backend, full_name, task["title"], jira_key=task.get("jira_key"))
        _wait_for_claude_ready(backend, full_name)
    if send_prompt and task.get("description") and bool(int(is_prompt)):
        _send_commands(backend, full_name, task["description"], auto_submit=False)
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


def _bare_name(screen_session: str) -> str:
    """Strip PID prefix from screen full_name (e.g. '1234.foo' → 'foo'). Idempotent."""
    if "." in screen_session:
        return screen_session.split(".", 1)[1]
    return screen_session


def resume_sessions(db_path: Path) -> int:
    """Recreate sessions for tasks with claude_session_id but no live session."""
    backend = get_backend()
    live = _live_sessions()
    live_names = {s["name"] for s in live.values()}
    live_full_names = set(live.keys())
    tasks = list_tasks(db_path)
    resumed = 0
    for t in tasks:
        if not t.get("claude_session_id"):
            continue
        name = session_name_for(t["id"], t.get("title"))
        stored = t.get("screen_session") or ""
        stored_bare = _bare_name(stored) if stored else ""
        if name in live_names or stored in live_names or stored in live_full_names or stored_bare in live_names:
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
    time.sleep(2)  # wait for claude --resume to initialize before attach
    full_name = _resolve_full_name(backend, name) or name
    update_kwargs: dict = dict(screen_session=full_name)
    if effective_cwd:
        update_kwargs["cwd"] = effective_cwd
    update_task(db_path, task_id, **update_kwargs)
    if task.get("title"):
        _wait_for_claude_ready(backend, full_name)
        _rename_claude_session(backend, full_name, task["title"])
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

    ignored = load_ignored_sessions()
    task_by_id = {t["id"]: t for t in tasks}
    imported = 0
    for full_name, s in live.items():
        if s["name"] in linked_names or full_name in linked_names:
            continue
        if s["name"] in ignored or full_name in ignored:
            continue
        # Try to relink a planner-owned session to its task by ID suffix
        relinked = _relink_by_id(db_path, s["name"], full_name, task_by_id)
        if relinked:
            continue
        # Skip planner-owned sessions (task-NNN) and the planner TUI session itself
        if s["name"].startswith(SESSION_NAME_PREFIX + "-") or s["name"] == "planner":
            continue
        add_task(db_path, source="screen", title=s["name"],
                 screen_session=full_name, horizon="this_week")
        imported += 1
    return imported


def _relink_by_id(db_path: Path, name: str, full_name: str,
                  task_by_id: dict) -> bool:
    """If session name contains -{task_id} (as prefix-id or prefix-id-slug), relink to task. Return True if relinked."""
    import re
    # Match both old format (planner-NNN) and new format (task-NNN or task-NNN-slug)
    m = re.search(r"-(\d+)(?:-|$)", name)
    if not m:
        return False
    task_id = int(m.group(1))
    if task_id not in task_by_id:
        return False
    update_task(db_path, task_id, screen_session=full_name)
    return True


def run_recurring_via_session(db_path: Path, task_dict: dict, prompt: str,
                              auto_submit: bool = False) -> None:
    """Populate prompt into a recurring task's session (submit only if auto_submit=True)."""
    backend = get_backend()
    if task_dict.get("screen_session") and task_dict.get("claude_session_id"):
        live = _live_sessions()
        name = task_dict["screen_session"]
        if any(s["name"] == name or s["full_name"] == name for s in live.values()):
            if not _wait_for_claude_ready(backend, name, timeout=2.0):
                # Session busy — skip this run
                return
            if _input_buffer_has_text(backend, name):
                # Prompt already populated — leave it alone
                return
            # Escape aborts any buffered input, then /clear resets context
            backend.send_raw(name, "\033")
            time.sleep(0.1)
            backend.send_input(name, "/clear")
            # Wait for /clear + SessionStart hooks to finish before populating
            time.sleep(1.5)
            _send_commands(backend, name, prompt, auto_submit=auto_submit)
            return
    full_name = launch_session(db_path, task_dict, send_prompt=False)
    _send_commands(backend, full_name, prompt, auto_submit=auto_submit)
