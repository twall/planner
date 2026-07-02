from textual.widgets import Static
from textual.widget import Widget
from textual.app import ComposeResult


class BriefingPanel(Widget):
    DEFAULT_CSS = """
    BriefingPanel {
        height: 5;
        border: solid $panel;
        padding: 0 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield Static("[dim]Daily briefing loading...[/dim]", id="briefing-content")

    def update(self, summaries: list[str]) -> None:
        text = "  ".join(summaries) if summaries else "[dim]No briefing data yet.[/dim]"
        self.query_one("#briefing-content", Static).update(text)
