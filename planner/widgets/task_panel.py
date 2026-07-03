import time
from pathlib import Path
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import Static
from textual.widget import Widget
from planner.db import list_tasks, update_task
from planner.config import DB_PATH
from planner.screen_monitor import SessionState

SPINNER_FRAMES = "⣾⣽⣻⢿⡿⣟⣯⣷"

HORIZON_CYCLE = ["today", "this_week"]

SOURCE_TAG = {
    "jira": "JIRA",
    "freeform": "·",
    "slack": "SLACK",
    "git": "BB",
    "bitbucket": "BB",
    "sentry": "SENTRY",
}


class TaskPanel(Widget):
    can_focus = False

    class TaskAction(Message):
        def __init__(self, task_id: int, action: str):
            super().__init__()
            self.task_id = task_id
            self.action = action

    class TaskSelected(Message):
        def __init__(self, task: dict | None):
            super().__init__()
            self.task = task

    class DeleteRequested(Message):
        def __init__(self, task: dict):
            super().__init__()
            self.task = task

    DEFAULT_CSS = """
    TaskPanel {
        height: 1fr;
        overflow-y: auto;
    }
    """

    def __init__(self, db_path: Path = DB_PATH):
        super().__init__()
        self.border_title = "Horizon"
        self._db_path = db_path
        self._tasks: list[dict] = []
        self._selected_id: int | None = None
        self._session_states: dict[str, SessionState] = {}
        self._show_done: bool = False

    def on_mount(self) -> None:
        # Redraw at ~4fps to animate spinners for ACTIVE sessions
        self.set_interval(0.25, self._maybe_spin)

    def _maybe_spin(self) -> None:
        if any(s.state == "ACTIVE" for s in self._session_states.values()):
            self._render_tasks()

    def update_sessions(self, sessions: list[SessionState]) -> None:
        self._session_states = {}
        for s in sessions:
            self._session_states[s.name] = s
            self._session_states[s.full_name] = s
        self._render_tasks()

    def _cursor_idx(self) -> int:
        """Resolve selected ID to current list index; fall back to 0."""
        for i, t in enumerate(self._tasks):
            if t["id"] == self._selected_id:
                return i
        return 0

    def compose(self) -> ComposeResult:
        yield Static(id="task-list-content")

    def toggle_show_done(self) -> None:
        self._show_done = not self._show_done
        self.border_title = "Horizon  [dim](showing done)[/dim]" if self._show_done else "Horizon"
        self.refresh_tasks()

    def refresh_tasks(self) -> None:
        prev_ids = [t["id"] for t in self._tasks]
        all_tasks = list_tasks(self._db_path)
        if self._show_done:
            # Show done disposable tasks alongside open ones
            self._tasks = [t for t in all_tasks
                           if t["status"] != "done" or t.get("disposable")]
        else:
            self._tasks = [t for t in all_tasks if t["status"] != "done"]
        task_ids = {t["id"] for t in self._tasks}
        if not self._tasks:
            self._selected_id = None
        elif self._selected_id not in task_ids:
            # Selected task gone (or never set) — move to neighbour by prior position
            old_idx = prev_ids.index(self._selected_id) if self._selected_id in prev_ids else 0
            clamped = min(old_idx, len(self._tasks) - 1)
            self._selected_id = self._tasks[clamped]["id"]
        # else: _selected_id still valid, keep it
        self._render_tasks()

    def select_by_id(self, task_id: int) -> None:
        ids = {t["id"] for t in self._tasks}
        if task_id in ids:
            self._selected_id = task_id
            self._render_tasks()

    def _emit_selected(self) -> None:
        self.post_message(self.TaskSelected(self._selected_task()))

    def _render_tasks(self) -> None:
        from planner.widgets.session_panel import STATE_COLORS
        cursor_idx = self._cursor_idx()
        lines = []
        cursor_line = 0

        builtins = [t for t in self._tasks if t["source"] == "builtin"]
        normal   = [t for t in self._tasks if t["source"] != "builtin"]

        current_horizon = None
        for i, t in enumerate(self._tasks):
            if t["source"] == "builtin":
                continue
            # Recompute flat index into self._tasks for cursor matching
            flat_i = self._tasks.index(t)
            if t["horizon"] != current_horizon:
                current_horizon = t["horizon"]
                heading = {"today": "TODAY", "this_week": "THIS WEEK"}.get(
                    current_horizon, current_horizon.upper()
                )
                lines.append(f"\n[bold]{heading}[/bold]")
            lines.append(self._render_row(t, flat_i == cursor_idx))
            if flat_i == cursor_idx:
                cursor_line = len(lines) - 1

        if builtins:
            lines.append("\n[bold]PERMANENT[/bold]")
            for t in builtins:
                flat_i = self._tasks.index(t)
                lines.append(self._render_row(t, flat_i == cursor_idx))
                if flat_i == cursor_idx:
                    cursor_line = len(lines) - 1

        content = "\n".join(lines) if lines else "[dim]No tasks.[/dim]"
        self.query_one("#task-list-content", Static).update(content)
        self.scroll_to(y=cursor_line, animate=False)
        self._emit_selected()

    def _render_row(self, t: dict, is_cursor: bool) -> str:
        from planner.widgets.session_panel import STATE_COLORS
        tag = SOURCE_TAG.get(t["source"], t["source"].upper())
        cursor = "▶ " if is_cursor else "  "
        jira = f"[{t['jira_key']}] " if t.get("jira_key") else f"[{tag}] "
        sess = self._session_states.get(t.get("screen_session", ""))
        if sess:
            color = STATE_COLORS.get(sess.state, "white")
            if sess.state == "ACTIVE":
                frame = SPINNER_FRAMES[int(time.time() * 4) % len(SPINNER_FRAMES)]
                badge = f"[green]{frame}[/green] "
            else:
                badge = f"[{color}]●[/{color}] "
        else:
            badge = "  "
        title = t["title"]
        if t.get("status") == "done":
            title = f"[dim strike]{title}[/strike][/dim]"
        return f"{cursor}{badge}{jira}{title}"

    def action_move_cursor_down(self) -> None:
        if not self._tasks:
            return
        idx = self._cursor_idx()
        self._selected_id = self._tasks[(idx + 1) % len(self._tasks)]["id"]
        self._render_tasks()

    def action_move_cursor_up(self) -> None:
        if not self._tasks:
            return
        idx = self._cursor_idx()
        self._selected_id = self._tasks[(idx - 1) % len(self._tasks)]["id"]
        self._render_tasks()

    def _selected_task(self) -> dict | None:
        idx = self._cursor_idx()
        return self._tasks[idx] if self._tasks else None

    LOCKED_SOURCES = {"jira", "builtin"}

    def action_move_task_up(self) -> None:
        self._swap_with_neighbour(-1)

    def action_move_task_down(self) -> None:
        self._swap_with_neighbour(1)

    def _swap_with_neighbour(self, direction: int) -> None:
        if not self._tasks:
            return
        idx = self._cursor_idx()
        neighbour_idx = idx + direction
        if neighbour_idx < 0 or neighbour_idx >= len(self._tasks):
            return
        a = self._tasks[idx]
        b = self._tasks[neighbour_idx]
        # Swap priorities; if crossing horizon boundary, adopt neighbour's horizon
        a_pri, b_pri = a["priority"], b["priority"]
        a_horizon, b_horizon = a["horizon"], b["horizon"]
        kwargs_a: dict = {"priority": b_pri}
        kwargs_b: dict = {"priority": a_pri}
        if a_horizon != b_horizon:
            kwargs_a["horizon"] = b_horizon
            kwargs_b["horizon"] = a_horizon
        update_task(self._db_path, a["id"], **kwargs_a)
        update_task(self._db_path, b["id"], **kwargs_b)
        self.refresh_tasks()
        self.select_by_id(a["id"])

    def action_mark_done(self) -> None:
        t = self._selected_task()
        if not t:
            return
        if t.get("source") in self.LOCKED_SOURCES:
            self.notify(f"Built-in task '{t['title']}' cannot be deleted.", severity="warning")
            return
        # If a live session exists, ask the app to confirm before killing
        if t.get("screen_session"):
            self.post_message(self.DeleteRequested(t))
            return
        update_task(self._db_path, t["id"], status="done", screen_session=None,
                    claude_session_id=None)
        self.refresh_tasks()

    def do_delete(self, task: dict) -> None:
        from planner.session_manager import kill_session
        if task.get("screen_session"):
            kill_session(task["screen_session"])
        update_task(self._db_path, task["id"], status="done", screen_session=None,
                    claude_session_id=None)
        self.refresh_tasks()

    def action_move_horizon(self) -> None:
        t = self._selected_task()
        if t:
            idx = HORIZON_CYCLE.index(t["horizon"]) if t["horizon"] in HORIZON_CYCLE else 0
            new_horizon = HORIZON_CYCLE[(idx + 1) % len(HORIZON_CYCLE)]
            update_task(self._db_path, t["id"], horizon=new_horizon)
            self.refresh_tasks()
