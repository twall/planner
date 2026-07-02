from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static, TextArea

from planner.config import DB_PATH
from planner.db import update_task


class TaskEditPane(Widget):
    class TaskSaved(Message):
        def __init__(self, task_id: int):
            super().__init__()
            self.task_id = task_id

    class EditCancelled(Message):
        pass

    class SessionAction(Message):
        def __init__(self, task_id: int, action: str):
            super().__init__()
            self.task_id = task_id
            self.action = action  # "start"

    DEFAULT_CSS = """
    TaskEditPane {
        height: 1fr;
        padding: 1 2;
        overflow-y: auto;
    }
    TaskEditPane Input {
        margin-bottom: 1;
    }
    #edit-desc {
        height: 8;
        margin-bottom: 1;
    }
    #edit-actions {
        height: 3;
        margin-top: 1;
    }
    #edit-actions Button {
        margin-right: 1;
    }
    #edit-hint {
        height: 1;
        margin-bottom: 1;
    }
    """

    def __init__(self, db_path=DB_PATH):
        super().__init__()
        self._db_path = db_path
        self._current_task: dict | None = None
        self._editing = False

    def compose(self) -> ComposeResult:
        yield Static("[dim]No task selected.[/dim]", id="edit-placeholder")
        with Vertical(id="edit-form"):
            yield Static("", id="edit-hint")
            yield Label("Title")
            yield Input(placeholder="Task title", id="edit-title")
            yield Label("Description / Prompt")
            yield TextArea("", id="edit-desc", soft_wrap=True)
            yield Label("Working Directory")
            yield Input(placeholder="~/path/to/project  (blank = choose on start)", id="edit-cwd")
            yield Static("", id="edit-disposable-hint")
            with Horizontal(id="edit-actions"):
                yield Button("Start Session", id="btn-start")

    def on_mount(self) -> None:
        self.query_one("#edit-form").display = False
        for btn in self.query(Button):
            btn.can_focus = False

    def show(self, task: dict | None) -> None:
        self._current_task = task
        self._editing = False
        placeholder = self.query_one("#edit-placeholder", Static)
        form = self.query_one("#edit-form")
        if task is None:
            placeholder.display = True
            form.display = False
            return
        placeholder.display = False
        form.display = True
        self._refresh_fields()
        self._set_fields_readonly(True)
        self._update_hint()

    def _refresh_fields(self) -> None:
        if not self._current_task:
            return
        self.query_one("#edit-title", Input).value = self._current_task.get("title", "")
        desc = self._current_task.get("description") or ""
        ta = self.query_one("#edit-desc", TextArea)
        ta.load_text(desc)
        self.query_one("#edit-cwd", Input).value = self._current_task.get("cwd") or ""
        has_session = bool(self._current_task.get("screen_session"))
        btn = self.query_one("#btn-start")
        btn.display = not has_session
        self.query_one("#edit-cwd", Input).disabled = has_session
        self._update_disposable_hint()

    def _update_disposable_hint(self) -> None:
        if not self._current_task:
            return
        is_disp = bool(self._current_task.get("disposable"))
        marker = "[bold green]✓[/bold green]" if is_disp else "[ ]"
        hint = self.query_one("#edit-disposable-hint", Static)
        hint.update(f"[dim]{marker} Disposable  (hide on done, kept for retrieval)[/dim]")

    def _toggle_disposable(self) -> None:
        if not self._current_task or not self._editing:
            return
        new_val = not bool(self._current_task.get("disposable"))
        self._current_task["disposable"] = int(new_val)
        self._update_disposable_hint()

    def _set_fields_readonly(self, readonly: bool) -> None:
        for inp in self.query(Input):
            inp.disabled = readonly
        self.query_one("#edit-desc", TextArea).read_only = readonly

    def _update_hint(self) -> None:
        hint = self.query_one("#edit-hint", Static)
        if not self._current_task:
            hint.update("")
        elif self._editing:
            hint.update("[dim][bold]● EDITING[/bold]  esc: exit field  ·  ctrl+s: save  ·  ctrl+d: toggle disposable  ·  tab: next[/dim]")
        else:
            has_session = bool(self._current_task.get("screen_session"))
            if self._current_task.get("source") == "builtin":
                session_hint = "" if has_session else "  ·  ctrl+s: start session"
                hint.update(f"[dim][italic]built-in task[/italic]  ·  ←/→: switch pane{session_hint}[/dim]")
            else:
                session_hint = "" if has_session else "  ·  ctrl+s: start session"
                hint.update(f"[dim]enter: edit  ·  ←/→: switch pane{session_hint}[/dim]")

    def enter_edit(self) -> None:
        if not self._current_task or self._editing:
            return
        if self._current_task.get("source") == "builtin":
            return
        self._editing = True
        self._set_fields_readonly(False)
        btn = self.query_one("#btn-start", Button)
        if btn.display:
            btn.can_focus = True
        self._update_hint()
        self.query_one("#edit-title", Input).focus()

    def _exit_edit(self) -> None:
        self._editing = False
        self._set_fields_readonly(True)
        self.query_one("#btn-start", Button).can_focus = False
        self._update_hint()

    def _save(self) -> None:
        if not self._current_task:
            return
        tid = self._current_task["id"]
        title = self.query_one("#edit-title", Input).value.strip()
        desc = self.query_one("#edit-desc", TextArea).text.strip()
        cwd = self.query_one("#edit-cwd", Input).value.strip()
        disposable = int(bool(self._current_task.get("disposable")))
        if title:
            update_task(self._db_path, tid, title=title,
                        description=desc if desc else None,
                        cwd=cwd if cwd else None,
                        disposable=disposable)
        self._exit_edit()
        self.post_message(self.TaskSaved(tid))

    def _cancel(self) -> None:
        self._refresh_fields()
        self._exit_edit()
        self.post_message(self.EditCancelled())

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if not self._editing:
            return
        event.stop()
        # Tab to next field from title/cwd; ctrl+s or explicit save handles final save
        if event.input.id == "edit-title":
            self.query_one("#edit-desc", TextArea).focus()
        elif event.input.id == "edit-cwd":
            self._save()

    def on_key(self, event) -> None:
        if not self._editing:
            return
        focused = self.app.focused
        in_textarea = isinstance(focused, TextArea)

        if event.key == "ctrl+s":
            event.stop()
            self._save()
        elif event.key == "ctrl+d" and not in_textarea:
            event.stop()
            self._toggle_disposable()
        elif event.key == "escape":
            event.stop()
            if in_textarea:
                # Leave textarea, move to next field
                self.screen.focus_next()
            else:
                self._cancel()
        elif event.key in ("down", "up") and not in_textarea:
            event.stop()
            if event.key == "down":
                self.screen.focus_next()
            else:
                self.screen.focus_previous()
        elif event.key == "space" and isinstance(focused, Button):
            event.stop()
            focused.press()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if not self._current_task:
            return
        tid = self._current_task["id"]
        if event.button.id == "btn-start":
            # Save any in-progress edits before launching so description is current
            if self._editing:
                self._save()
            self.post_message(self.SessionAction(tid, "start"))

    @property
    def editing(self) -> bool:
        return self._editing
