from rich.text import Text

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
            width = max(self.content_size.width - 2, 20)
            lines = session.last_lines[-30:] if session.last_lines else []
            # Build as Rich Text to avoid markup parser touching raw session output
            t = Text()
            t.append(f"● {session.full_name}  {session.state}", style=color)
            claude_id = task.get("claude_session_id") if task else None
            if claude_id:
                t.append(f"  claude:{claude_id[:8]}", style="dim")
            t.append(f"\n{'─' * 40}\n")
            if lines:
                for i, line in enumerate(lines):
                    if i:
                        t.append("\n")
                    t.append(line[:width])  # plain append — no markup parsing
            else:
                t.append("(no output)", style="dim")
            out.update(t)
            if session.state == "NEEDS PERMISSION":
                hint.update("[dim]enter: attach  ·  shift+enter: accept selected option[/dim]")
            else:
                hint.update("[dim]enter: attach to session[/dim]")
        else:
            t = Text()
            t.append(task["title"], style="bold")
            from planner.scheduler import RECURRING_SOURCES
            if task.get("source") in RECURRING_SOURCES:
                from planner.db import get_last_run
                from planner.config import DB_PATH
                last = get_last_run(DB_PATH, task["source"])
                t.append("\n")
                t.append(f"last run: {last}" if last else "never run", style="dim")
            desc = task.get("description")
            if desc:
                t.append("\n\n")
                t.append(desc)
            else:
                t.append("\n\n")
                t.append("No description.", style="dim")
            out.update(t)
            hint.update("[dim]→: task pane  ·  enter: run now  ·  ctrl+s: start session[/dim]")
