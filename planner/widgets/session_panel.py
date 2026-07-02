from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import ListView, ListItem, Label
from planner.screen_monitor import SessionState

STATE_COLORS = {
    "NEEDS PERMISSION": "bold red",
    "NEEDS INPUT": "bold yellow",
    "IDLE": "dim",
    "ACTIVE": "green",
    "ATTACHED": "bold cyan",
}


class SessionPanel(ListView):
    class SessionSelected(Message):
        def __init__(self, full_name: str):
            super().__init__()
            self.full_name = full_name

    class SessionPreview(Message):
        def __init__(self, full_name: str, lines: list[str]):
            super().__init__()
            self.full_name = full_name
            self.lines = lines

    def __init__(self):
        super().__init__()
        self._sessions: list[SessionState] = []
        self._id_to_idx: dict[str, int] = {}
        self._gen = 0
        self._selected_name: str | None = None  # stable across refreshes

    def _idx_for_name(self, name: str) -> int | None:
        for i, s in enumerate(self._sessions):
            if s.full_name == name:
                return i
        return None

    def update(self, sessions: list[SessionState]) -> None:
        self._sessions = sessions
        self._id_to_idx = {}
        self._gen += 1
        self.clear()
        restore_idx = None
        for i, s in enumerate(sessions):
            item_id = f"sess-{s.pid}-{self._gen}"
            self._id_to_idx[item_id] = i
            color = STATE_COLORS.get(s.state, "white")
            idle_str = f"  {int(s.idle_seconds // 60)}m" if s.state == "IDLE" and s.idle_seconds >= 60 else ""
            label = f"[{color}]● {s.name:<16} {s.state}{idle_str}[/{color}]"
            self.append(ListItem(Label(label), id=item_id))
            if s.full_name == self._selected_name:
                restore_idx = i
        # Restore selection after DOM settles
        if restore_idx is not None:
            self.call_after_refresh(setattr, self, "index", restore_idx)

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        idx = self._id_to_idx.get(event.item.id)
        if idx is not None:
            self._selected_name = self._sessions[idx].full_name
            self.post_message(self.SessionSelected(self._sessions[idx].full_name))

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        idx = self._id_to_idx.get(event.item.id) if event.item else None
        if idx is not None:
            self._selected_name = self._sessions[idx].full_name

    def action_preview(self) -> None:
        # Use tracked selected name, fall back to highlighted index, then first session
        idx = None
        if self._selected_name:
            idx = self._idx_for_name(self._selected_name)
        if idx is None:
            idx = self.index if self.index is not None else 0
        if self._sessions and idx < len(self._sessions):
            s = self._sessions[idx]
            self.post_message(self.SessionPreview(s.full_name, s.last_lines))
