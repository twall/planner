# Unified Task-Session Model Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** Merge session and task into a single unified list where tasks optionally own a Claude Code screen session; support launch, resume-after-reboot, recurring task re-run, and lightweight in-pane interaction.

**Architecture:** Tasks are primary; sessions are attached to tasks. On startup, orphan screen sessions are imported as tasks. The right pane has three modes: Content (live output + input), Task (metadata editor + session controls), Todo (checklist). Session naming is deterministic (`planner-{task_id}`); Claude session IDs are stored for reboot recovery via `claude --resume`.

**Tech Stack:** Python 3.11, Textual 0.x, SQLite, GNU screen, Claude Code CLI (`claude --session-id`, `claude --resume`)

## Global Constraints

- Python 3.11 only
- No aiosqlite — sync sqlite3 throughout
- `screen -X stuff` for sending input to sessions (nopty/pexpect)
- Claude session ID is a UUID; generated with `uuid.uuid4()`
- Screen session name: `planner-{task_id}` (always)
- `claude --session-id {uuid}` for new sessions; `claude --resume {uuid}` for recovery
- Textual: no blocking calls on main thread — use `run_worker(thread=True)` + `call_from_thread`
- All DB migrations via `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern (SQLite-safe)

---

### Task 1: DB schema migration + session management helpers

**Files:**
- Modify: `planner/db.py`
- Modify: `planner/screen_monitor.py`
- Create: `planner/session_manager.py`
- Test: `tests/test_session_manager.py`

**Interfaces:**
- Produces:
  - `db.update_task(db_path, task_id, claude_session_id=..., screen_session=...)` — extended allowed fields
  - `session_manager.launch_session(task: dict) -> str` — launches screen+claude, returns screen session name
  - `session_manager.resume_sessions(db_path)` — recovers dead sessions on startup
  - `session_manager.kill_session(screen_session: str) -> None`
  - `session_manager.send_input(screen_session: str, text: str) -> None`
  - `session_manager.import_orphan_sessions(db_path) -> int` — returns count imported

- [ ] **Step 1: Add DB columns**

In `planner/db.py`, extend `SCHEMA` and `init_db`:

```python
# Add to SCHEMA string (after existing CREATE TABLE):
ALTER_TASKS_SESSION = """
ALTER TABLE tasks ADD COLUMN claude_session_id TEXT;
ALTER TABLE tasks ADD COLUMN session_pid TEXT;
"""

def init_db(db_path: Path) -> None:
    with _conn(db_path) as conn:
        conn.executescript(SCHEMA)
        # Add new columns if missing (SQLite has no IF NOT EXISTS for columns)
        for col, typedef in [("claude_session_id", "TEXT"), ("session_pid", "TEXT")]:
            try:
                conn.execute(f"ALTER TABLE tasks ADD COLUMN {col} {typedef}")
            except Exception:
                pass  # already exists
```

Also extend `update_task` allowed set:
```python
allowed = {"title", "description", "priority", "horizon", "status",
           "screen_session", "claude_session_id", "session_pid"}
```

- [ ] **Step 2: Write failing test**

```python
# tests/test_session_manager.py
import uuid
from pathlib import Path
import pytest
from planner.db import init_db, add_task, list_tasks
from planner.session_manager import SESSION_NAME_PREFIX, session_name_for

def test_session_name_for():
    assert session_name_for(42) == "planner-42"

def test_db_stores_claude_session_id(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    tid = add_task(db, source="freeform", title="Test")
    from planner.db import update_task
    uid = str(uuid.uuid4())
    update_task(db, tid, claude_session_id=uid, screen_session=session_name_for(tid))
    tasks = list_tasks(db)
    assert tasks[0]["claude_session_id"] == uid
    assert tasks[0]["screen_session"] == session_name_for(tid)
```

- [ ] **Step 3: Run test — expect fail** (session_manager doesn't exist yet)

```bash
cd ~/planner && source .venv/bin/activate && pytest tests/test_session_manager.py -v 2>&1 | head -20
```

- [ ] **Step 4: Create `planner/session_manager.py`**

```python
import subprocess
import uuid
from pathlib import Path
from planner.db import add_task, list_tasks, update_task
from planner.screen_monitor import parse_screen_ls

SESSION_NAME_PREFIX = "planner"


def session_name_for(task_id: int) -> str:
    return f"{SESSION_NAME_PREFIX}-{task_id}"


def _live_sessions() -> dict[str, dict]:
    """Return dict of full_name -> session dict from screen -ls."""
    try:
        result = subprocess.run(["screen", "-ls"], capture_output=True, text=True, timeout=5)
        return {s["full_name"]: s for s in parse_screen_ls(result.stdout)}
    except Exception:
        return {}


def launch_session(db_path: Path, task: dict) -> str:
    """Launch a new screen+claude session for task. Returns screen session name."""
    task_id = task["id"]
    name = session_name_for(task_id)
    session_id = str(uuid.uuid4())
    cmd = ["screen", "-S", name, "-dm", "claude", "--session-id", session_id]
    if task.get("description"):
        # Pass initial prompt via -p flag (non-interactive first message)
        cmd = ["screen", "-S", name, "-dm", "claude",
               "--session-id", session_id, "-p", task["description"]]
    subprocess.run(cmd, timeout=10)
    update_task(db_path, task_id, screen_session=name, claude_session_id=session_id)
    return name


def resume_sessions(db_path: Path) -> int:
    """Recreate screen sessions for tasks with claude_session_id but no live session."""
    live = _live_sessions()
    tasks = list_tasks(db_path)
    resumed = 0
    for t in tasks:
        if not t.get("claude_session_id"):
            continue
        name = session_name_for(t["id"])
        if any(s["name"] == name or s["full_name"].endswith(f".{name}") for s in live.values()):
            continue  # already running
        cmd = ["screen", "-S", name, "-dm", "claude", "--resume", t["claude_session_id"]]
        subprocess.run(cmd, timeout=10)
        update_task(db_path, t["id"], screen_session=name)
        resumed += 1
    return resumed


def kill_session(screen_session: str) -> None:
    subprocess.run(["screen", "-S", screen_session, "-X", "quit"],
                   capture_output=True, timeout=5)


def send_input(screen_session: str, text: str) -> None:
    """Send text to a screen session's stdin."""
    # Escape backslashes for screen stuff command
    escaped = text.replace("\\", "\\\\")
    subprocess.run(
        ["screen", "-S", screen_session, "-X", "stuff", escaped + "\n"],
        capture_output=True, timeout=5
    )


def import_orphan_sessions(db_path: Path) -> int:
    """Import screen sessions not linked to any task. Returns count added."""
    live = _live_sessions()
    tasks = list_tasks(db_path)
    linked = {t["screen_session"] for t in tasks if t.get("screen_session")}
    # Also match by planner-{id} pattern
    linked_names = set()
    for name in linked:
        linked_names.add(name)
        # Strip PID prefix: "12345.planner-3" -> "planner-3"
        if "." in name:
            linked_names.add(name.split(".", 1)[1])

    imported = 0
    for full_name, s in live.items():
        if s["name"] in linked_names or full_name in linked_names:
            continue
        tid = add_task(db_path, source="screen", title=s["name"],
                       screen_session=full_name, horizon="backlog")
        imported += 1
    return imported
```

- [ ] **Step 5: Run tests — expect pass**

```bash
pytest tests/test_session_manager.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Commit**

```bash
git add planner/db.py planner/session_manager.py tests/test_session_manager.py
git commit -m "feat: db schema + session_manager for launch/resume/import"
```

---

### Task 2: Startup import + reboot recovery wired into app

**Files:**
- Modify: `planner/app.py`

**Interfaces:**
- Consumes: `session_manager.import_orphan_sessions`, `session_manager.resume_sessions`
- Produces: on `on_mount`, orphans imported and dead sessions recovered before first render

- [ ] **Step 1: Write failing test**

```python
# tests/test_startup_import.py
from unittest.mock import patch, MagicMock
from planner.db import init_db, list_tasks

def test_import_orphan_creates_task(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    fake_sessions = [{"pid": "999", "name": "my-session",
                      "full_name": "999.my-session", "attached": False}]
    with patch("planner.session_manager.parse_screen_ls", return_value=fake_sessions), \
         patch("subprocess.run"):
        from planner.session_manager import import_orphan_sessions
        count = import_orphan_sessions(db)
    assert count == 1
    tasks = list_tasks(db)
    assert tasks[0]["title"] == "my-session"
    assert tasks[0]["source"] == "screen"
```

- [ ] **Step 2: Run test — expect fail**

```bash
pytest tests/test_startup_import.py -v
```

- [ ] **Step 3: Wire into `_startup` in app.py**

```python
async def _startup(self) -> None:
    from planner.session_manager import import_orphan_sessions, resume_sessions
    import_orphan_sessions(DB_PATH)
    resume_sessions(DB_PATH)
    self.query_one(TaskPanel).refresh_tasks()
    self.query_one("#loading").add_class("visible")
    self.run_worker(self._scheduler.run_all_due, thread=True, name="startup")
```

- [ ] **Step 4: Run test — expect pass**

```bash
pytest tests/test_startup_import.py -v
```

- [ ] **Step 5: Commit**

```bash
git add planner/app.py tests/test_startup_import.py
git commit -m "feat: import orphan sessions + resume dead sessions on startup"
```

---

### Task 3: Unified task list — session state badge in left column

**Files:**
- Modify: `planner/widgets/task_panel.py`
- Modify: `planner/app.py` (pass sessions to task panel on refresh)

**Interfaces:**
- Consumes: `SessionState` list from `ScreenMonitor`
- Produces: `TaskPanel.update_sessions(sessions: list[SessionState])` — task panel merges session state into display

- [ ] **Step 1: Add `update_sessions` to TaskPanel**

```python
# In task_panel.py
from planner.screen_monitor import SessionState

class TaskPanel(Widget):
    # ... existing code ...
    
    def __init__(self, db_path=DB_PATH):
        super().__init__()
        self._db_path = db_path
        self._tasks: list[dict] = []
        self._selected_id: int | None = None
        self._session_states: dict[str, SessionState] = {}  # screen_session -> state

    def update_sessions(self, sessions: list[SessionState]) -> None:
        self._session_states = {s.name: s for s in sessions}
        # Also index by full_name
        for s in sessions:
            self._session_states[s.full_name] = s
        self._render_tasks()
```

In `_render_tasks`, show state badge on tasks with sessions:

```python
def _render_tasks(self) -> None:
    from planner.widgets.session_panel import STATE_COLORS
    cursor_idx = self._cursor_idx()
    lines = []
    cursor_line = 0
    current_horizon = None
    for i, t in enumerate(self._tasks):
        if t["horizon"] != current_horizon:
            current_horizon = t["horizon"]
            heading = {"today": "TODAY", "this_week": "THIS WEEK",
                       "backlog": "BACKLOG"}.get(current_horizon, current_horizon.upper())
            lines.append(f"\n[bold]{heading}[/bold]")
        
        # Session badge
        sess = self._session_states.get(t.get("screen_session", ""))
        if sess:
            color = STATE_COLORS.get(sess.state, "white")
            badge = f"[{color}]●[/{color}] "
        else:
            badge = "  "
        
        cursor = "▶ " if i == cursor_idx else "  "
        tag = SOURCE_TAG.get(t["source"], t["source"].upper())
        jira = f"[{t['jira_key']}] " if t.get("jira_key") else f"[{tag}] "
        lines.append(f"{cursor}{badge}{jira}{t['title']}")
        if i == cursor_idx:
            cursor_line = len(lines) - 1
    content = "\n".join(lines) if lines else "[dim]No tasks.[/dim]"
    self.query_one("#task-list-content", Static).update(content)
    self.scroll_to(y=cursor_line, animate=False)
    self._emit_selected()
```

- [ ] **Step 2: Wire `update_sessions` in app `_refresh_sessions`**

```python
def _refresh_sessions(self) -> None:
    sessions = self._monitor.get_sessions()
    self.query_one(TaskPanel).update_sessions(sessions)
    # ... existing detail pane refresh ...
```

Remove `SessionPanel` from compose (or keep as optional — see note below).

**Note:** Keep `SessionPanel` for now but make it hidden by default; it can be toggled. Remove from layout in a follow-up.

- [ ] **Step 3: Manual test** — launch planner, verify tasks with sessions show colored dot.

- [ ] **Step 4: Commit**

```bash
git add planner/widgets/task_panel.py planner/app.py
git commit -m "feat: session state badge in unified task list"
```

---

### Task 4: Right pane — Content / Task / Todo modes

**Files:**
- Create: `planner/widgets/content_pane.py`
- Create: `planner/widgets/task_edit_pane.py`
- Modify: `planner/widgets/task_detail_panel.py` → replace with `RightPane` controller
- Modify: `planner/app.py`

**Interfaces:**
- `ContentPane.show(task, session)` — updates output + sets session for input
- `ContentPane.on_input_submitted` → calls `send_input(session, text)`
- `TaskEditPane.show(task)` → populates edit fields
- `TaskEditPane.on_save` → posts `TaskSaved(task_id, fields)` message
- `RightPane.set_task(task, session)` — updates active sub-pane
- `RightPane.set_mode(mode: str)` — switches between "content"/"task"/"todo"

- [ ] **Step 1: Create `ContentPane`**

```python
# planner/widgets/content_pane.py
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static, Input
from textual.containers import Vertical
from planner.screen_monitor import SessionState
from planner.session_manager import send_input
from planner.widgets.session_panel import STATE_COLORS


class ContentPane(Widget):
    DEFAULT_CSS = """
    ContentPane {
        height: 1fr;
        padding: 0 1;
    }
    #session-output {
        height: 1fr;
        overflow-y: auto;
    }
    #session-input {
        height: 3;
        border-top: solid $panel;
        margin-top: 1;
    }
    """

    def __init__(self):
        super().__init__()
        self._task: dict | None = None
        self._session: SessionState | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[dim]No task selected.[/dim]", id="session-output")
            yield Input(placeholder="Send input to session…", id="session-input")

    def show(self, task: dict | None, session: SessionState | None) -> None:
        self._task = task
        self._session = session
        out = self.query_one("#session-output", Static)
        inp = self.query_one("#session-input", Input)

        if task is None:
            out.update("[dim]No task selected.[/dim]")
            inp.display = False
            return

        if session:
            color = STATE_COLORS.get(session.state, "white")
            header = f"[{color}]● {session.full_name}  {session.state}[/{color}]\n{'─'*40}\n"
            tail = "\n".join(session.last_lines[-30:]) if session.last_lines else "[dim](no output)[/dim]"
            out.update(header + tail)
            inp.display = True
            inp.placeholder = f"Send to {session.name}…"
        else:
            # No session: show task description as "ready to launch" view
            desc = task.get("description") or "[dim]No description. Press 's' to start a session.[/dim]"
            out.update(f"[bold]{task['title']}[/bold]\n\n{desc}")
            inp.display = False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text or not self._session:
            return
        send_input(self._session.full_name, text)
```

- [ ] **Step 2: Create `TaskEditPane`**

```python
# planner/widgets/task_edit_pane.py
from textual.app import ComposeResult
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Static, Input, Select, Button
from textual.containers import Vertical, Horizontal
from planner.db import update_task
from planner.config import DB_PATH


class TaskEditPane(Widget):
    class TaskSaved(Message):
        def __init__(self, task_id: int):
            super().__init__()
            self.task_id = task_id

    class SessionAction(Message):
        def __init__(self, task_id: int, action: str):
            super().__init__()
            self.task_id = task_id
            self.action = action  # "start" | "kill"

    DEFAULT_CSS = """
    TaskEditPane {
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    .field-row { height: 3; margin-bottom: 1; }
    .action-row { height: 3; margin-top: 1; }
    """

    def __init__(self, db_path=DB_PATH):
        super().__init__()
        self._db_path = db_path
        self._task: dict | None = None

    def compose(self) -> ComposeResult:
        yield Static("[dim]No task selected.[/dim]", id="edit-placeholder")
        with Vertical(id="edit-form"):
            yield Input(placeholder="Title", id="edit-title")
            yield Input(placeholder="Description", id="edit-desc")
            with Horizontal(classes="action-row"):
                yield Button("Save", id="btn-save", variant="primary")
                yield Button("Start Session", id="btn-start")
                yield Button("Kill Session", id="btn-kill", variant="error")
                yield Button("Delete Task", id="btn-delete", variant="error")

    def show(self, task: dict | None) -> None:
        self._task = task
        placeholder = self.query_one("#edit-placeholder", Static)
        form = self.query_one("#edit-form")
        if task is None:
            placeholder.display = True
            form.display = False
            return
        placeholder.display = False
        form.display = True
        self.query_one("#edit-title", Input).value = task.get("title", "")
        self.query_one("#edit-desc", Input).value = task.get("description") or ""
        has_session = bool(task.get("screen_session"))
        self.query_one("#btn-start").disabled = has_session
        self.query_one("#btn-kill").disabled = not has_session

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self._task:
            return
        tid = self._task["id"]
        if event.button.id == "btn-save":
            title = self.query_one("#edit-title", Input).value.strip()
            desc = self.query_one("#edit-desc", Input).value.strip()
            if title:
                update_task(self._db_path, tid, title=title,
                            description=desc if desc else None)
            self.post_message(self.TaskSaved(tid))
        elif event.button.id == "btn-start":
            self.post_message(self.SessionAction(tid, "start"))
        elif event.button.id == "btn-kill":
            self.post_message(self.SessionAction(tid, "kill"))
        elif event.button.id == "btn-delete":
            update_task(self._db_path, tid, status="done")
            self.post_message(self.TaskSaved(tid))
```

- [ ] **Step 3: Replace `TaskDetailPanel` with `RightPane` controller**

Replace `planner/widgets/task_detail_panel.py`:

```python
# planner/widgets/task_detail_panel.py  (repurposed as RightPane)
from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static
from textual.containers import Vertical
from planner.screen_monitor import SessionState
from planner.widgets.content_pane import ContentPane
from planner.widgets.task_edit_pane import TaskEditPane


class RightPane(Widget):
    DEFAULT_CSS = """
    RightPane {
        height: 1fr;
        width: 1fr;
    }
    #pane-tabs {
        height: 1;
        padding: 0 1;
    }
    ContentPane { display: block; height: 1fr; }
    TaskEditPane { display: none; height: 1fr; }
    RightPane.mode-task ContentPane { display: none; }
    RightPane.mode-task TaskEditPane { display: block; }
    """

    def __init__(self):
        super().__init__()
        self._mode = "content"

    def compose(self) -> ComposeResult:
        yield Static("", id="pane-tabs")
        yield ContentPane()
        yield TaskEditPane()

    def _update_tabs(self) -> None:
        tabs = {"content": "[bold]Content[/bold]", "task": "Task"}
        label = "  ".join(
            f"[reverse]{v}[/reverse]" if k == self._mode else v
            for k, v in tabs.items()
        )
        self.query_one("#pane-tabs", Static).update(label)

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.remove_class("mode-task")
        if mode == "task":
            self.add_class("mode-task")
        self._update_tabs()

    def set_task(self, task: dict | None, session: SessionState | None = None) -> None:
        self.query_one(ContentPane).show(task, session)
        self.query_one(TaskEditPane).show(task)
        self._update_tabs()
```

- [ ] **Step 4: Update `app.py`**

- Replace `TaskDetailPanel` import with `RightPane`
- Update `compose`: replace `TaskDetailPanel` with `RightPane`
- Add bindings `c` → content mode, `t` → task/edit mode
- Handle `TaskEditPane.TaskSaved` → refresh tasks
- Handle `TaskEditPane.SessionAction` → launch/kill session
- Update `on_task_panel_task_selected` → call `right_pane.set_task(task, session)`
- Update `_refresh_sessions` → call `right_pane.set_task(...)` for current selection

Key app additions:
```python
Binding("c", "pane_content", "Content", show=False),
Binding("t", "pane_task", "Task/Edit", show=False),

def action_pane_content(self) -> None:
    self.query_one(RightPane).set_mode("content")

def action_pane_task(self) -> None:
    self.query_one(RightPane).set_mode("task")

def on_task_edit_pane_task_saved(self, event) -> None:
    self.query_one(TaskPanel).refresh_tasks()
    self.notify("Saved")

def on_task_edit_pane_session_action(self, event) -> None:
    from planner.session_manager import launch_session, kill_session
    tasks = list_tasks(DB_PATH)
    task = next((t for t in tasks if t["id"] == event.task_id), None)
    if not task:
        return
    if event.action == "start":
        self.run_worker(lambda: launch_session(DB_PATH, task), thread=True)
        self.notify(f"Starting session for {task['title']}…")
    elif event.action == "kill":
        kill_session(task["screen_session"])
        update_task(DB_PATH, event.task_id, screen_session=None)
        self.query_one(TaskPanel).refresh_tasks()
        self.notify("Session killed")
```

- [ ] **Step 5: Manual test** — launch planner, verify c/t switch modes, edit a task, start/kill session.

- [ ] **Step 6: Commit**

```bash
git add planner/widgets/content_pane.py planner/widgets/task_edit_pane.py \
        planner/widgets/task_detail_panel.py planner/app.py
git commit -m "feat: right pane Content/Task modes with session input + edit"
```

---

### Task 5: Recurring task integration with session lifecycle

**Files:**
- Modify: `planner/scheduler.py`
- Modify: `planner/app.py`

**Goal:** Recurring tasks (slack, bitbucket, sentry) use session_manager — `/clear` + prompt if session exists, launch new if not.

- [ ] **Step 1: Add `run_task_via_session` to `session_manager.py`**

```python
def run_recurring_via_session(db_path: Path, task_dict: dict, prompt: str) -> None:
    """Run a recurring task: reuse existing session (/clear + prompt) or launch new."""
    if task_dict.get("screen_session") and task_dict.get("claude_session_id"):
        # Check session is still live
        live = _live_sessions()
        name = task_dict["screen_session"]
        if any(s["name"] == name or s["full_name"].endswith(f".{name}")
               for s in live.values()):
            send_input(name, "/clear")
            import time; time.sleep(1)  # let /clear process
            send_input(name, prompt)
            return
    # No live session — launch new
    launch_session(db_path, task_dict)
    import time; time.sleep(2)  # let claude start
    send_input(session_name_for(task_dict["id"]), prompt)
```

- [ ] **Step 2: Find or create task DB record for each recurring task**

In `scheduler.py`, add helper that returns (or creates) a task for a recurring task config:

```python
def _ensure_task(self, recurring: RecurringTask) -> dict:
    from planner.db import list_tasks, add_task
    tasks = list_tasks(self._db_path)
    match = next((t for t in tasks if t.get("source") == recurring.name
                  or t.get("title") == recurring.label), None)
    if match:
        return match
    tid = add_task(self._db_path, source=recurring.name,
                   title=recurring.label, description=recurring.prompt,
                   horizon="today")
    tasks = list_tasks(self._db_path)
    return next(t for t in tasks if t["id"] == tid)
```

Modify `run_task` in `Scheduler` to use session when available:

```python
def run_task(self, task: RecurringTask) -> list[dict]:
    from planner.session_manager import run_recurring_via_session
    task_dict = self._ensure_task(task)
    run_recurring_via_session(self._db_path, task_dict, task.prompt)
    self.set_last_run(task.name)
    return []
```

- [ ] **Step 3: Manual test** — run `s` (Slack digest) in planner, verify session starts and `/clear` + prompt sent.

- [ ] **Step 4: Commit**

```bash
git add planner/scheduler.py planner/session_manager.py
git commit -m "feat: recurring tasks launch/reuse claude sessions via screen"
```