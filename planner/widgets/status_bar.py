import datetime
from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class StatusBar(Widget):
    DEFAULT_CSS = """
    StatusBar {
        height: 1;
        background: $panel;
        padding: 0 1;
    }
    """

    def __init__(self):
        super().__init__()
        self._sync_label = "never"
        self._sync_time: datetime.datetime | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="status-content")

    def set_sync_status(self, label: str, seconds_ago: int) -> None:
        # seconds_ago param kept for API compat but ignored — we store the timestamp
        self._sync_label = label
        self._sync_time = datetime.datetime.now()
        self._refresh_content()

    def on_mount(self) -> None:
        self.set_interval(1, self._refresh_content)

    def _refresh_content(self) -> None:
        now = datetime.datetime.now()
        date_str = now.strftime("%a %b %d")
        time_str = now.strftime("%H:%M")
        if self._sync_time is not None:
            elapsed = int((now - self._sync_time).total_seconds())
            mins = elapsed // 60
            sync_str = f"{self._sync_label}: {mins}m ago" if mins > 0 else f"{self._sync_label}: just now"
        else:
            sync_str = "never"
        text = f"  PLANNER  [{date_str}]  [last sync: {sync_str}]  {time_str}"
        self.query_one("#status-content", Static).update(text)
