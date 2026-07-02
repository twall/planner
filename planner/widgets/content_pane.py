from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import Static

from planner.screen_monitor import SessionState
from planner.widgets.session_panel import STATE_COLORS


class ContentPane(Widget):
    """Read-only session output view. Enter attaches to the session."""

    DEFAULT_CSS = """
    ContentPane {
        height: 1fr;
        padding: 0 1;
        overflow: hidden;
    }
    #session-output {
        height: 1fr;
        overflow: hidden auto;
    }
    #session-hint {
        height: 1;
    }
    """

    def __init__(self):
        super().__init__()
        self._session: SessionState | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("[dim]No task selected.[/dim]", id="session-output")
            yield Static("", id="session-hint")

    def show(self, task: dict | None, session: SessionState | None) -> None:
        self._session = session
        out = self.query_one("#session-output", Static)
        hint = self.query_one("#session-hint", Static)

        if task is None:
            out.update("[dim]No task selected.[/dim]")
            hint.update("")
            return

        if session:
            color = STATE_COLORS.get(session.state, "white")
            header = f"[{color}]● {session.full_name}  {session.state}[/{color}]\n{'─' * 40}\n"
            # Escape Rich markup in raw session output to prevent bleed-through
            from rich.markup import escape
            lines = session.last_lines[-30:] if session.last_lines else []
            tail = "\n".join(escape(l) for l in lines) if lines else "[dim](no output)[/dim]"
            out.update(header + tail)
            hint.update("[dim]enter: attach to session[/dim]")
        else:
            desc = task.get("description") or "[dim]No description.[/dim]"
            out.update(f"[bold]{task['title']}[/bold]\n\n{desc}")
            hint.update("[dim]→: task pane  ·  ctrl+s: start session[/dim]")
