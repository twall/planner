from textual.app import ComposeResult
from textual.widget import Widget
from textual.widgets import Static

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
        background: $panel;
    }
    ContentPane {
        height: 1fr;
        display: block;
    }
    TaskEditPane {
        height: 1fr;
        display: none;
    }
    RightPane.mode-task ContentPane { display: none; }
    RightPane.mode-task TaskEditPane { display: block; }
    """

    def __init__(self):
        super().__init__()
        self._mode = "content"
        self._current_task: dict | None = None
        self._current_session: SessionState | None = None

    def compose(self) -> ComposeResult:
        yield Static("", id="pane-tabs")
        yield ContentPane()
        yield TaskEditPane()

    def on_mount(self) -> None:
        self._update_tabs()

    def _update_tabs(self) -> None:
        items = [("content", "Content [c]"), ("task", "Edit [t]")]
        parts = []
        for key, label in items:
            if key == self._mode:
                parts.append(f"[reverse bold] {label} [/reverse bold]")
            else:
                parts.append(f" {label} ")
        self.query_one("#pane-tabs", Static).update("  ".join(parts))

    def set_mode(self, mode: str) -> None:
        self._mode = mode
        self.remove_class("mode-task")
        if mode == "task":
            self.add_class("mode-task")
        self._update_tabs()
        self._push_to_panes()

    def set_task(self, task: dict | None, session: SessionState | None = None) -> None:
        ep = self.query_one(TaskEditPane)
        if ep.editing:
            # Don't interrupt an active edit; only refresh session output
            self._current_session = session
            self.query_one(ContentPane).show(self._current_task, session)
            return
        self._current_task = task
        self._current_session = session
        self._push_to_panes()

    def _push_to_panes(self) -> None:
        self.query_one(ContentPane).show(self._current_task, self._current_session)
        self.query_one(TaskEditPane).show(self._current_task, has_live_session=bool(self._current_session))
