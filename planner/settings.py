import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

from planner.config import (
    SETTINGS_PATH,
    SCREEN_POLL_INTERVAL,
    SCREEN_IDLE_THRESHOLD,
)

DEFAULT_KEYMAP = {
    "attach":       "enter",
    "preview":      "p",
    "new_task":     "n",
    "mark_done":    "d",
    "move_horizon": "m",
    "sync_jira":    "j",
    "run_bitbucket": "b",
    "run_slack":    "s",
    "run_all":      "R",
    "toggle_theme": "T",
    "show_help":    "h",
    "quit":         "q",
    "cursor_down":  "J",
    "cursor_up":    "K",
}


@dataclass
class Settings:
    # Any Textual built-in theme name, or "auto" to detect from COLORFGBG.
    # Built-ins: textual-dark, textual-light, nord, gruvbox, catppuccin-mocha,
    #   dracula, tokyo-night, monokai, flexoki, catppuccin-latte, solarized-light,
    #   solarized-dark, rose-pine, atom-one-dark, ansi-dark, ansi-light, ...
    theme: str = "auto"
    # Tuning
    screen_poll_interval: int = SCREEN_POLL_INTERVAL
    screen_idle_threshold: int = SCREEN_IDLE_THRESHOLD
    # UI
    session_panel_width: int = 30
    default_task_horizon: str = "today"
    # Keybindings — action name → key string
    keymap: dict = field(default_factory=lambda: dict(DEFAULT_KEYMAP))
    # Integration config — empty by default, set in settings.json
    jira_projects: list = field(default_factory=list)
    sentry_projects: list = field(default_factory=list)
    git_repos: list = field(default_factory=list)
    slack_channels: list = field(default_factory=list)


def load_settings(path: Path = SETTINGS_PATH) -> Settings:
    if not path.exists():
        s = Settings()
        save_settings(s, path)
        return s
    with open(path) as f:
        data = json.load(f)
    s = Settings()
    for k in ("theme", "screen_poll_interval", "screen_idle_threshold",
              "jira_sync_interval", "session_panel_width", "default_task_horizon",
              "jira_projects", "sentry_projects", "git_repos", "slack_channels"):
        if k in data:
            setattr(s, k, data[k])
    if "keymap" in data:
        s.keymap = {**DEFAULT_KEYMAP, **data["keymap"]}
    return s


def save_settings(s: Settings, path: Path = SETTINGS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(asdict(s), f, indent=2)
