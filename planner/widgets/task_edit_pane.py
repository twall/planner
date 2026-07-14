from pathlib import Path
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static, TextArea

from planner.config import DB_PATH
from planner.db import update_task
from planner.scheduler import RECURRING_SOURCES


class TaskEditPane(Widget):
    can_focus = True  # allows self.focus() to return focus here after edit

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
    #btn-disposable {
        margin-bottom: 1;
        height: 1;
        border: none;
        background: transparent;
        min-width: 0;
    }
    #btn-is-prompt {
        margin-bottom: 1;
        height: 1;
        border: none;
        background: transparent;
        min-width: 0;
    }
    #schedule-section {
        margin-top: 1;
    }
    """

    def __init__(self, db_path=DB_PATH):
        super().__init__()
        self._db_path = db_path
        self._current_task: dict | None = None
        self._editing = False
        self._has_live_session = False

    def compose(self) -> ComposeResult:
        yield Static("[dim]No session selected.[/dim]", id="edit-placeholder")
        with Vertical(id="edit-form"):
            yield Static("", id="edit-hint")
            yield Label("Title")
            yield Input(placeholder="Session title", id="edit-title")
            yield Label("Description / Prompt")
            yield TextArea("", id="edit-desc", soft_wrap=True)
            yield Label("Working Directory")
            yield Input(placeholder="~/path/to/project  (blank = choose on start)", id="edit-cwd")
            yield Button("[ ] Use as Claude Code prompt", id="btn-is-prompt")
            yield Button("[ ] Disposable  (hide on done, kept for retrieval)", id="btn-disposable")
            with Vertical(id="schedule-section"):
                yield Label("Schedule")
                yield Input(placeholder="frequency: daily | weekly | interval", id="edit-frequency")
                yield Input(placeholder="time: HH:MM  (earliest run time)", id="edit-time")
                yield Input(placeholder="days: mon,tue,wed,thu,fri  (blank = every day)", id="edit-days")
                yield Input(placeholder="interval_hours: e.g. 4  (for interval frequency)", id="edit-interval")
            with Horizontal(id="edit-actions"):
                yield Button("Start Session", id="btn-start")

    def on_mount(self) -> None:
        self.query_one("#edit-form").display = False
        for btn_id in ("#btn-start", "#btn-disposable", "#btn-is-prompt"):
            self.query_one(btn_id, Button).can_focus = False
        self.query_one("#edit-desc", TextArea).can_focus = False

    def show(self, task: dict | None, has_live_session: bool = False) -> None:
        self._current_task = task
        self._editing = False
        self._has_live_session = has_live_session
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

    def _is_recurring(self) -> bool:
        return bool(self._current_task and
                    self._current_task.get("source") in RECURRING_SOURCES)

    def _refresh_fields(self) -> None:
        if not self._current_task:
            return
        if self._editing:
            return
        self.query_one("#edit-title", Input).value = self._current_task.get("title", "")
        desc = self._current_task.get("description") or ""
        ta = self.query_one("#edit-desc", TextArea)
        ta.load_text(desc)
        self.query_one("#edit-cwd", Input).value = self._current_task.get("cwd") or ""

        # Show "Start Session" when no live session is active
        btn_start = self.query_one("#btn-start", Button)
        btn_start.display = not self._has_live_session

        # Schedule section — only for recurring tasks; values come from DB columns
        sched = self.query_one("#schedule-section")
        sched.display = self._is_recurring()
        if self._is_recurring():
            t = self._current_task
            self.query_one("#edit-frequency", Input).value = t.get("rt_frequency") or "daily"
            self.query_one("#edit-time", Input).value = t.get("rt_time") or ""
            self.query_one("#edit-days", Input).value = t.get("rt_days") or ""
            iv = t.get("rt_interval_hours")
            self.query_one("#edit-interval", Input).value = str(iv) if iv is not None else ""

        self._update_disposable_btn()
        self._update_is_prompt_btn()

    def _update_disposable_btn(self) -> None:
        if not self._current_task:
            return
        is_disp = bool(self._current_task.get("disposable"))
        mark = "[bold green]✓[/bold green]" if is_disp else "[ ]"
        self.query_one("#btn-disposable", Button).label = f"{mark} Disposable  (hide on done, kept for retrieval)"

    def _update_is_prompt_btn(self) -> None:
        if not self._current_task:
            return
        is_prompt = self._current_task.get("is_prompt", 1)
        if is_prompt is None:
            is_prompt = 1
        is_prompt = bool(int(is_prompt))
        mark = "[bold green]✓[/bold green]" if is_prompt else "[ ]"
        self.query_one("#btn-is-prompt", Button).label = f"{mark} Use as Claude Code prompt"

    def _toggle_disposable(self) -> None:
        if not self._current_task or not self._editing:
            return
        new_val = not bool(self._current_task.get("disposable"))
        self._current_task["disposable"] = int(new_val)
        self._update_disposable_btn()

    def _toggle_is_prompt(self) -> None:
        if not self._current_task or not self._editing:
            return
        cur = self._current_task.get("is_prompt", 1)
        if cur is None:
            cur = 1
        new_val = not bool(int(cur))
        self._current_task["is_prompt"] = int(new_val)
        self._update_is_prompt_btn()

    def _set_fields_readonly(self, readonly: bool) -> None:
        for inp in self.query(Input):
            inp.disabled = readonly
        ta = self.query_one("#edit-desc", TextArea)
        ta.read_only = readonly
        ta.can_focus = not readonly

    def _update_hint(self) -> None:
        hint = self.query_one("#edit-hint", Static)
        if not self._current_task:
            hint.update("")
        elif self._editing:
            hint.update("[dim][bold]● EDITING[/bold]  ctrl+s: save  ·  esc: cancel  ·  ctrl+d: disposable  ·  tab: next[/dim]")
        else:
            if self._current_task.get("source") == "builtin":
                session_hint = "" if self._has_live_session else "  ·  ctrl+s: start session"
                hint.update(f"[dim][italic]built-in task[/italic]  ·  ←/→: switch pane{session_hint}[/dim]")
            else:
                session_hint = "" if self._has_live_session else "  ·  ctrl+s: start session"
                hint.update(f"[dim]enter: edit  ·  ←/→: switch pane{session_hint}[/dim]")

    def enter_edit(self) -> None:
        if not self._current_task or self._editing:
            return
        if self._current_task.get("source") == "builtin":
            return
        self._editing = True
        self._set_fields_readonly(False)
        for btn_id in ("#btn-start", "#btn-disposable", "#btn-is-prompt"):
            self.query_one(btn_id, Button).can_focus = True
        self._update_hint()
        self.query_one("#edit-title", Input).focus()

    def _exit_edit(self) -> None:
        self._editing = False
        self._set_fields_readonly(True)
        for btn_id in ("#btn-start", "#btn-disposable", "#btn-is-prompt"):
            self.query_one(btn_id, Button).can_focus = False
        self._update_hint()
        self.focus()

    def _save(self) -> None:
        if not self._current_task:
            return
        tid = self._current_task["id"]
        title = self.query_one("#edit-title", Input).value.strip()
        desc = self.query_one("#edit-desc", TextArea).text.strip()
        cwd_raw = self.query_one("#edit-cwd", Input).value.strip()
        cwd = str(Path(cwd_raw).expanduser()) if cwd_raw else ""
        disposable = int(bool(self._current_task.get("disposable")))
        is_prompt_val = self._current_task.get("is_prompt", 1)
        if is_prompt_val is None:
            is_prompt_val = 1
        is_prompt = int(bool(int(is_prompt_val)))
        kwargs: dict = dict(description=desc if desc else None,
                            cwd=cwd if cwd else None,
                            disposable=disposable,
                            is_prompt=is_prompt)
        if title:
            kwargs["title"] = title
        if self._is_recurring():
            freq = self.query_one("#edit-frequency", Input).value.strip()
            rt_time = self.query_one("#edit-time", Input).value.strip()
            days_raw = self.query_one("#edit-days", Input).value.strip()
            iv_raw = self.query_one("#edit-interval", Input).value.strip()
            kwargs["rt_frequency"] = freq or "daily"
            kwargs["rt_time"] = rt_time or None
            kwargs["rt_days"] = days_raw or None
            try:
                kwargs["rt_interval_hours"] = float(iv_raw) if iv_raw else None
            except ValueError:
                pass
        update_task(self._db_path, tid, **kwargs)
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
        if event.input.id == "edit-title":
            self._save()
        elif event.input.id == "edit-cwd":
            if self._is_recurring():
                self.query_one("#edit-frequency", Input).focus()
            else:
                self._save()
        elif event.input.id == "edit-interval":
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
            if self._editing:
                self._save()
            self.post_message(self.SessionAction(tid, "start"))
        elif event.button.id == "btn-disposable":
            event.stop()
            self._toggle_disposable()
        elif event.button.id == "btn-is-prompt":
            event.stop()
            self._toggle_is_prompt()

    @property
    def editing(self) -> bool:
        return self._editing
