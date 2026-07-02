import datetime
import json
import os
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, Label, ListItem, ListView, LoadingIndicator, Static, TextArea

from planner.config import DB_PATH, PLANNER_ROOT, SCREEN_POLL_INTERVAL
from planner.state import save_state, load_state
from planner.db import init_db, list_tasks, update_task
from planner.jira import JiraClient
from planner.scheduler import Scheduler, load_jira_sync_interval
from planner.settings import Settings, load_settings, save_settings
from planner.screen_monitor import ScreenMonitor
from planner.widgets.briefing_panel import BriefingPanel
from planner.widgets.status_bar import StatusBar
from planner.widgets.task_detail_panel import RightPane
from planner.widgets.task_edit_pane import TaskEditPane
from planner.widgets.task_panel import TaskPanel


_SKILLS_SRC = Path(__file__).parent.parent / "skills"
_COMMANDS_DIR = Path.home() / ".claude" / "commands"
_INBOX_PATH = Path.home() / ".planner" / "inbox.json"

_BUILTIN_TASKS = [
    {
        "source": "builtin",
        "title": "Improve Planner",
        "description": (
            "Improve the planner application. Make local code changes, "
            "run tests, commit, and submit PRs or report issues on GitHub."
        ),
        "cwd": str(PLANNER_ROOT),
        "horizon": "backlog",
        "priority": 5,
    },
    {
        "source": "builtin",
        "title": "Organize Tasks",
        "description": (
            "Review all current planner tasks. "
            "Reclassify horizons (today/this_week/backlog), adjust priorities (1=urgent, 5=low), "
            "and rename titles for clarity. "
            "Use the /planner-organize skill to propose and apply changes interactively."
        ),
        "cwd": None,
        "horizon": "backlog",
        "priority": 5,
    },
]


def _purge_stale_planner_session_tasks(db_path: Path) -> None:
    """Remove tasks imported as orphans that match the old 'planner-{id}' naming scheme."""
    import re
    from planner.db import list_tasks, update_task
    for t in list_tasks(db_path):
        if t.get("source") == "screen" and re.fullmatch(r"planner-\d+", t.get("title", "")):
            update_task(db_path, t["id"], status="done")


def _install_skills() -> None:
    """Symlink planner skills into ~/.claude/commands/ on first run."""
    _COMMANDS_DIR.mkdir(parents=True, exist_ok=True)
    for skill_file in _SKILLS_SRC.glob("*.md"):
        link = _COMMANDS_DIR / skill_file.name
        if not link.exists():
            link.symlink_to(skill_file.resolve())


def _ingest_inbox(db_path: Path) -> int:
    """Import queued tasks from ~/.planner/inbox.json. Returns count ingested."""
    if not _INBOX_PATH.exists():
        return 0
    try:
        entries = json.loads(_INBOX_PATH.read_text())
    except Exception:
        return 0
    if not isinstance(entries, list) or not entries:
        _INBOX_PATH.unlink(missing_ok=True)
        return 0
    from planner.db import add_task
    count = 0
    for entry in entries:
        if not isinstance(entry, dict) or not entry.get("title"):
            continue
        add_task(
            db_path,
            source="claude",
            title=entry["title"],
            description=entry.get("description"),
            horizon=entry.get("horizon", "this_week"),
            priority=entry.get("priority", 3),
        )
        count += 1
    _INBOX_PATH.unlink(missing_ok=True)
    return count


KEYMAP_TEXT = """\
 ↑ / ↓    Move task cursor (also J / K)
 enter    Attach to session (content pane) / edit task (task pane)
 ctrl+s   Start session for selected task (task pane)

 c        Right pane: Content / session output
 t        Right pane: Task / edit metadata
 n        New task
 d        Delete task (and kill session if any)
 D        Toggle show completed disposable tasks
 m        Move task horizon (today → this week)
 j        Sync JIRA
 b        Re-run PR review
 s        Re-run Slack digest
 R        Re-run all recurring tasks
 T        Change theme
 h / ?    Show this help
 q        Quit
"""


class KeymapModal(ModalScreen):
    CSS = """
    KeymapModal {
        align: center middle;
    }
    #keymap-box {
        width: 60;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    """
    BINDINGS = [("escape", "dismiss", "Close"), ("q", "dismiss", "Close"),
                ("h", "dismiss", "Close"), ("?", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        with Static(id="keymap-box"):
            yield Label("[bold]Keybindings[/bold]\n")
            yield Label(KEYMAP_TEXT)


class AddTaskModal(ModalScreen[str | None]):
    CSS = """
    AddTaskModal {
        align: center middle;
    }
    #add-task-box {
        width: 60;
        height: auto;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    #add-task-box Input {
        margin-top: 1;
    }
    """
    BINDINGS = [("escape", "dismiss", "Cancel")]

    def compose(self) -> ComposeResult:
        with Static(id="add-task-box"):
            yield Label("[bold]New Task[/bold]  [dim](esc to cancel · /task also works in any Claude session)[/dim]")
            yield Input(placeholder="Task title…", id="task-title-input")

    def on_mount(self) -> None:
        self.query_one("#task-title-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        title = event.value.strip()
        self.dismiss(title if title else None)



def _decode_project_dirs() -> list[Path]:
    """Decode ~/.claude/projects/ dir names back to filesystem paths, newest first."""
    projects_root = Path.home() / ".claude" / "projects"
    if not projects_root.exists():
        return []
    results = []
    for entry in sorted(projects_root.iterdir(), key=lambda p: -p.stat().st_mtime):
        if not entry.is_dir():
            continue
        # Encoding: leading slash → leading hyphen, each '/' → '-'
        # e.g. -Users-twall-plex-rd → /Users/twall/plex/rd
        name = entry.name
        if name.startswith("-"):
            decoded = Path("/" + name[1:].replace("-", "/"))
        else:
            decoded = Path(name.replace("-", "/"))
        if decoded.exists():
            results.append(decoded)
    return results


class ProjectPickerModal(ModalScreen[str | None]):
    """Pick a working directory for the new Claude session."""

    CSS = """
    ProjectPickerModal {
        align: center middle;
    }
    #picker-box {
        width: 70;
        height: auto;
        max-height: 80%;
        border: solid $accent;
        padding: 1 2;
        background: $surface;
    }
    #picker-list {
        height: auto;
        max-height: 20;
        margin-top: 1;
    }
    #picker-input {
        margin-top: 1;
        display: none;
    }
    #picker-input.visible {
        display: block;
    }
    """

    BINDINGS = [("escape", "dismiss", "Cancel")]

    def __init__(self, projects: list[Path]):
        super().__init__()
        self._projects = projects
        self._other_mode = False

    def compose(self) -> ComposeResult:
        with Vertical(id="picker-box"):
            yield Label("[bold]Choose working directory[/bold]  [dim]↑↓ navigate · enter select · esc cancel[/dim]")
            items = [ListItem(Label(str(p)), id=f"proj-{i}") for i, p in enumerate(self._projects)]
            items.append(ListItem(Label("[dim]Other…[/dim]"), id="proj-other"))
            yield ListView(*items, id="picker-list")
            yield Input(placeholder="Path…", id="picker-input")

    def on_mount(self) -> None:
        self.query_one(ListView).focus()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        if event.item.id == "proj-other":
            self._other_mode = True
            inp = self.query_one("#picker-input", Input)
            inp.add_class("visible")
            inp.focus()
        else:
            idx = int(event.item.id.split("-", 1)[1])
            self.dismiss(str(self._projects[idx]))

    def on_input_submitted(self, event: Input.Submitted) -> None:
        path = event.value.strip()
        self.dismiss(path if path else None)


class ConfirmDeleteModal(ModalScreen[bool]):
    """Confirm killing a live session before deleting a task."""

    CSS = """
    ConfirmDeleteModal {
        align: center middle;
    }
    #confirm-box {
        width: 60;
        height: auto;
        border: solid $error;
        padding: 1 2;
        background: $surface;
    }
    #confirm-buttons {
        margin-top: 1;
        height: 3;
    }
    #confirm-buttons Button {
        margin-right: 1;
    }
    """

    BINDINGS = [("escape", "dismiss_false", "Cancel"), ("y", "dismiss_true", "Yes")]

    def __init__(self, task_title: str):
        super().__init__()
        self._title = task_title

    def compose(self) -> ComposeResult:
        with Static(id="confirm-box"):
            yield Label(f"[bold red]Kill session and delete task?[/bold red]\n\n{self._title}")
            with Horizontal(id="confirm-buttons"):
                yield Button("Yes, delete (y)", id="btn-yes", variant="error")
                yield Button("Cancel (esc)", id="btn-cancel")

    def action_dismiss_false(self) -> None:
        self.dismiss(False)

    def action_dismiss_true(self) -> None:
        self.dismiss(True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "btn-yes")


class PlannerApp(App):
    CSS = """
    Input:focus {
        border: tall green;
    }
    #main-row {
        height: 1fr;
    }
    TaskPanel {
        width: 35;
        border: solid $panel;
        height: 100%;
    }
    RightPane {
        width: 1fr;
        border: solid $panel;
        height: 100%;
    }
    BriefingPanel {
        height: 5;
    }
    #loading {
        height: 1;
        display: none;
    }
    #loading.visible {
        display: block;
    }
    """

    BINDINGS = [
        Binding("up", "cursor_up", "Up", show=False),
        Binding("down", "cursor_down", "Down", show=False),

        Binding("n", "new_task", "New task"),
        Binding("d", "mark_done", "Delete"),
        Binding("m", "move_horizon", "Move horizon"),
        Binding("j", "sync_jira", "Sync JIRA"),
        Binding("b", "run_bitbucket", "PRs"),
        Binding("s", "run_slack", "Slack digest"),
        Binding("R", "run_all", "Run all"),
        Binding("u", "upgrade", "Upgrade", show=False),
        Binding("q", "quit", "Quit"),
        Binding("T", "change_theme", "Theme", show=False),
        Binding("h", "show_help", "Help", show=False),
        Binding("?", "show_help", "Help", show=False),
        Binding("J", "cursor_down", "Down", show=False),
        Binding("K", "cursor_up", "Up", show=False),
        Binding("D", "toggle_done", "Show done", show=False),
    ]

    def __init__(self):
        super().__init__()
        self._settings: Settings = load_settings()
        self._monitor = ScreenMonitor(
            poll_interval=self._settings.screen_poll_interval,
            idle_threshold=self._settings.screen_idle_threshold,
        )
        self._scheduler = Scheduler(DB_PATH)
        self._jira_client: JiraClient | None = self._make_jira_client()
        self._apply_theme(self._settings.theme)

    def _apply_theme(self, theme: str) -> None:
        if theme == "auto":
            colorfgbg = os.environ.get("COLORFGBG", "")
            if colorfgbg:
                try:
                    bg = int(colorfgbg.split(";")[-1])
                    self.dark = bg < 8
                except ValueError:
                    pass
        else:
            self.theme = theme

    def watch_theme(self, theme: str) -> None:
        if self._settings.theme != "auto":
            self._settings.theme = theme
            save_settings(self._settings)

    def _make_jira_client(self) -> JiraClient | None:
        token = os.environ.get("JIRA_API_TOKEN")
        cloud_id = os.environ.get("JIRA_CLOUD_ID", "")
        if not token or not cloud_id:
            return None
        return JiraClient(token=token, cloud_id=cloud_id)

    def compose(self) -> ComposeResult:
        yield StatusBar()
        with Horizontal(id="main-row"):
            yield TaskPanel(DB_PATH)
            yield RightPane()
        yield BriefingPanel()
        yield LoadingIndicator(id="loading")
        yield Footer()

    def on_mount(self) -> None:
        import signal
        init_db(DB_PATH)
        self._monitor.start()
        self._apply_keymap()
        self.set_interval(self._settings.screen_poll_interval, self._refresh_sessions)
        self.set_interval(load_jira_sync_interval(), self.action_sync_jira)
        self.set_interval(10, self._check_recurring)
        self.set_interval(86400, self._run_update_check)
        self.call_after_refresh(self._startup)
        if self._jira_client:
            self.call_after_refresh(self.action_sync_jira)
        # Clean exit on SIGHUP (screen/tmux detach) so state is saved
        signal.signal(signal.SIGHUP, lambda *_: self.call_from_thread(self._clean_exit))

    def _apply_keymap(self) -> None:
        from planner.settings import DEFAULT_KEYMAP
        action_descriptions = {
            "attach_session": ("Attach", True),

            "new_task": ("New task", True),
            "mark_done": ("Delete", True),
            "move_horizon": ("Move horizon", True),
            "sync_jira": ("Sync JIRA", True),
            "run_bitbucket": ("PRs", True),
            "run_slack": ("Slack digest", True),
            "run_all": ("Run all", True),
            "show_help": ("Help", False),
            "quit": ("Quit", True),
            "cursor_down": ("Down", False),
            "cursor_up": ("Up", False),
        }
        for action, key in self._settings.keymap.items():
            default_key = DEFAULT_KEYMAP.get(action)
            if default_key and key != default_key and action in action_descriptions:
                desc, show = action_descriptions[action]
                self.bind(key, action, description=desc, show=show)

    async def _startup(self) -> None:
        from planner.db import add_task, list_tasks
        from planner.session_manager import import_orphan_sessions, resume_sessions
        _install_skills()
        ingested = _ingest_inbox(DB_PATH)
        if ingested:
            self.call_after_refresh(self.notify, f"Imported {ingested} task(s) from inbox")
        self.run_worker(self._check_for_update, thread=True, name="update-check")
        # Ensure each recurring task config has an open DB task entry (restore if done)
        from planner.db import _conn
        with _conn(DB_PATH) as conn:
            all_rows = [dict(r) for r in conn.execute("SELECT * FROM tasks").fetchall()]
        for bt in _BUILTIN_TASKS:
            match = next((t for t in all_rows if t["source"] == "builtin"
                          and t["title"] == bt["title"]), None)
            if match is None:
                add_task(DB_PATH, source="builtin", title=bt["title"],
                         description=bt["description"], cwd=bt["cwd"],
                         horizon=bt["horizon"], priority=bt["priority"])
            elif match["status"] == "done":
                update_task(DB_PATH, match["id"], status="open")
        for rt in self._scheduler.load_tasks():
            match = next((t for t in all_rows
                          if t["title"] == rt.label or t["source"] == rt.name), None)
            if match is None:
                add_task(DB_PATH, source=rt.name, title=rt.label,
                         description=rt.prompt, horizon="today", priority=2)
            elif match["status"] == "done":
                update_task(DB_PATH, match["id"], status="open")
        import_orphan_sessions(DB_PATH)
        _purge_stale_planner_session_tasks(DB_PATH)
        resume_sessions(DB_PATH)
        # Eager poll so session states are populated before first render
        self._monitor._poll()
        panel = self.query_one(TaskPanel)
        panel.update_sessions(self._monitor.get_sessions())
        panel.refresh_tasks()
        ui = load_state()
        if ui.get("selected_task_id"):
            panel.select_by_id(ui["selected_task_id"])
        self.query_one("#loading").add_class("visible")
        self.run_worker(self._scheduler.run_all_due, thread=True, name="startup")

    def on_worker_state_changed(self, event) -> None:
        from textual.worker import WorkerState
        if event.state in (WorkerState.SUCCESS, WorkerState.ERROR, WorkerState.CANCELLED):
            self.query_one("#loading").remove_class("visible")
        if event.state == WorkerState.SUCCESS:
            self.query_one(TaskPanel).refresh_tasks()
            self._update_briefing()

    def _update_briefing(self) -> None:
        from planner.db import get_last_run
        summaries = []
        for task_name, label in [("slack", "Slack"), ("git", "PRs"), ("sentry", "Sentry")]:
            last = get_last_run(DB_PATH, task_name)
            if last:
                summaries.append(f"{label}: last run {last}")
        self.query_one(BriefingPanel).update(summaries)

    def _get_session_for_task(self, task: dict):
        if not task or not task.get("screen_session"):
            return None
        sessions = self._monitor.get_sessions()
        return next(
            (s for s in sessions if s.name == task["screen_session"]
             or s.full_name == task["screen_session"]), None
        )

    def _refresh_sessions(self) -> None:
        sessions = self._monitor.get_sessions()
        self.query_one(TaskPanel).update_sessions(sessions)
        selected = self.query_one(TaskPanel)._selected_task()
        if selected:
            session = next(
                (s for s in sessions if s.name == selected.get("screen_session")
                 or s.full_name == selected.get("screen_session")), None
            ) if selected.get("screen_session") else None
            self.query_one(RightPane).set_task(selected, session)

    def _run_update_check(self) -> None:
        self.run_worker(self._check_for_update, thread=True, name="update-check")

    def _check_for_update(self) -> None:
        from planner.updater import check_for_update
        outdated, _local, remote = check_for_update()
        if outdated and remote:
            self.call_from_thread(self.query_one(StatusBar).set_update_available, remote)

    def action_upgrade(self) -> None:
        if isinstance(self.focused, (Input, TextArea)):
            return
        sb = self.query_one(StatusBar)
        if not sb.update_available:
            return
        from planner.updater import do_upgrade

        async def _run() -> None:
            import asyncio
            loop = asyncio.get_event_loop()
            self.notify("Upgrading…", timeout=60)
            success, output = await loop.run_in_executor(None, do_upgrade)
            if success:
                self.notify("Upgraded! Restarting…", severity="information", timeout=3)
                self._snapshot()
                self.call_later(self.exit, result="__restart__")
            else:
                self.notify(f"Upgrade failed: {output[:120]}", severity="error", timeout=15)

        self.run_worker(_run)

    def _check_recurring(self) -> None:
        now = datetime.datetime.now()
        if now.hour >= 8:
            due = [t for t in self._scheduler.load_tasks() if self._scheduler.should_run_today(t.name)]
            if due:
                self.run_worker(self._scheduler.run_all_due, thread=True)

    def action_sync_jira(self) -> None:
        if not self._jira_client:
            self.notify("JIRA_API_TOKEN not set", severity="warning")
            return
        self.run_worker(self._do_jira_sync, thread=True)

    def _do_jira_sync(self) -> None:
        from planner.db import upsert_jira_task
        try:
            issues = self._jira_client.fetch_assigned_issues(self._settings.jira_projects)
            for issue in issues:
                upsert_jira_task(DB_PATH, **issue)
            self.call_from_thread(self.notify, f"Synced {len(issues)} JIRA issues")
            self.call_from_thread(self.query_one(TaskPanel).refresh_tasks)
            self.call_from_thread(self.query_one(StatusBar).set_sync_status, "JIRA", 0)
        except Exception as e:
            self.call_from_thread(self.notify, f"JIRA sync failed: {e}", severity="error")

    def _run_named_task(self, name: str, label: str) -> None:
        task = next((t for t in self._scheduler.load_tasks() if t.name == name), None)
        if task is None:
            self.notify(f"Task '{name}' not found in tasks.json", severity="warning")
            return
        self.run_worker(lambda: self._scheduler.run_task(task), thread=True)
        self.notify(f"Running {label}...")

    def action_run_slack(self) -> None:
        self._run_named_task("slack", "Slack digest")

    def action_run_bitbucket(self) -> None:
        self._run_named_task("git", "PR review")

    def action_run_all(self) -> None:
        self.run_worker(self._scheduler.run_all_due, thread=True)
        self.notify("Running all recurring tasks...")

    def action_attach_session(self) -> None:
        self._handle_enter()

    def on_task_panel_task_selected(self, event: TaskPanel.TaskSelected) -> None:
        task = event.task
        session = self._get_session_for_task(task)
        self.query_one(RightPane).set_task(task, session)

    def on_task_panel_delete_requested(self, event: TaskPanel.DeleteRequested) -> None:
        task = event.task
        def _confirmed(yes: bool) -> None:
            if yes:
                self.query_one(TaskPanel).do_delete(task)
        self.push_screen(ConfirmDeleteModal(task["title"]), _confirmed)

    def on_task_edit_pane_task_saved(self, event: TaskEditPane.TaskSaved) -> None:
        self.query_one(TaskPanel).refresh_tasks()
        self.notify("Saved")

    def on_task_edit_pane_edit_cancelled(self, event: TaskEditPane.EditCancelled) -> None:
        pass  # stay in task pane; hint already updated by TaskEditPane

    def on_task_edit_pane_session_action(self, event: TaskEditPane.SessionAction) -> None:
        tasks = list_tasks(DB_PATH)
        task = next((t for t in tasks if t["id"] == event.task_id), None)
        if not task:
            return
        if event.action == "start":
            self._prompt_start_session(task)

    def action_pane_content(self) -> None:
        self.query_one(RightPane).set_mode("content")

    def action_pane_task(self) -> None:
        self.query_one(RightPane).set_mode("task")


    def action_show_help(self) -> None:
        self.push_screen(KeymapModal())

    def action_mark_done(self) -> None:
        self.query_one(TaskPanel).action_mark_done()

    def action_toggle_done(self) -> None:
        self.query_one(TaskPanel).toggle_show_done()

    def action_move_horizon(self) -> None:
        self.query_one(TaskPanel).action_move_horizon()

    def action_new_task(self) -> None:
        from planner.db import add_task

        def _on_title(title: str | None) -> None:
            if not title:
                return
            add_task(DB_PATH, source="freeform", title=title,
                     horizon=self._settings.default_task_horizon, priority=3)
            self.query_one(TaskPanel).refresh_tasks()
            self.notify(f"Added: {title}")

        self.push_screen(AddTaskModal(), _on_title)

    def action_cursor_down(self) -> None:
        from textual.widgets import TextArea
        if isinstance(self.focused, (Input, TextArea)):
            return
        self.query_one(TaskPanel).action_move_cursor_down()

    def action_cursor_up(self) -> None:
        from textual.widgets import TextArea
        if isinstance(self.focused, (Input, TextArea)):
            return
        self.query_one(TaskPanel).action_move_cursor_up()

    def on_key(self, event) -> None:
        pass

    def key_enter(self, event) -> None:
        from textual.widgets import TextArea
        if isinstance(self.focused, (Input, TextArea)):
            return
        event.stop()
        self._handle_enter()

    def key_left(self, event) -> None:
        from textual.widgets import TextArea
        if isinstance(self.focused, (Input, TextArea)):
            return
        event.stop()
        self.action_pane_content()

    def key_right(self, event) -> None:
        from textual.widgets import TextArea
        if isinstance(self.focused, (Input, TextArea)):
            return
        event.stop()
        self.action_pane_task()

    def key_ctrl_s(self, event) -> None:
        from textual.widgets import TextArea
        if isinstance(self.focused, (Input, TextArea)):
            return
        right = self.query_one(RightPane)
        if right._mode != "task":
            return
        ep = right.query_one(TaskEditPane)
        if ep.editing or not ep._current_task:
            return
        btn = ep.query_one("#btn-start")
        if not btn.display:
            return
        event.stop()
        self._prompt_start_session(ep._current_task)

    def _prompt_start_session(self, task: dict) -> None:
        try:
            term_cols = os.get_terminal_size().columns
            term_rows = os.get_terminal_size().lines
        except OSError:
            term_cols, term_rows = 220, 50
        cols = max(80, term_cols - 39)
        rows = max(24, term_rows - 4)

        def _launch(cwd: str | None) -> None:
            if cwd is None:
                return
            cwd = str(Path(cwd).expanduser()) if cwd else None
            from planner.session_manager import launch_session
            from planner.backends import get_backend

            full_name_holder: list[str] = []

            async def _do_launch_and_attach() -> None:
                import asyncio
                loop = asyncio.get_event_loop()
                full_name = await loop.run_in_executor(
                    None, lambda: launch_session(DB_PATH, task, cwd=cwd, cols=cols, rows=rows)
                )
                if full_name:
                    self._snapshot()
                    self._monitor.stop()
                    self.exit(result=get_backend().attach_cmd(full_name))

            self.run_worker(_do_launch_and_attach)
            self.notify(f"Starting session for {task['title']}…")

        saved_cwd = task.get("cwd")
        if saved_cwd:
            _launch(saved_cwd)
        else:
            projects = _decode_project_dirs()
            self.push_screen(ProjectPickerModal(projects), _launch)

    def _clean_exit(self) -> None:
        self._snapshot()
        self._monitor.stop()
        self.exit()

    def _snapshot(self) -> None:
        task = self.query_one(TaskPanel)._selected_task()
        save_state(task["id"] if task else None)

    def _handle_enter(self) -> None:
        right = self.query_one(RightPane)
        if right._mode == "content":
            task = self.query_one(TaskPanel)._selected_task()
            if task:
                if task.get("screen_session"):
                    from planner.backends import get_backend
                    self._snapshot()
                    self._monitor.stop()
                    self.exit(result=get_backend().attach_cmd(task["screen_session"]))
                elif task.get("source") not in TaskPanel.LOCKED_SOURCES:
                    self._prompt_start_session(task)
        elif right._mode == "task":
            ep = right.query_one(TaskEditPane)
            if not ep.editing:
                ep.enter_edit()


def main():
    import sys
    result_file = sys.argv[1] if len(sys.argv) > 1 else None
    app = PlannerApp()
    result = app.run()
    if result and result_file:
        with open(result_file, "w") as f:
            f.write(result)
    elif result:
        print(result)


if __name__ == "__main__":
    main()
