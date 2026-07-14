import os
from pathlib import Path

PLANNER_ROOT = Path(os.environ.get("PLANNER_INSTALL_DIR", Path.home() / "planner"))
DB_PATH = PLANNER_ROOT / "data" / "tasks.db"
TASKS_CONFIG_PATH = PLANNER_ROOT / "sessions.json"
SETTINGS_PATH = PLANNER_ROOT / "settings.json"

STATE_PATH = Path.home() / ".planner" / "state.json"
IGNORED_SESSIONS_PATH = Path.home() / ".planner" / "ignored_sessions.json"

SCREEN_POLL_INTERVAL = 5
SCREEN_IDLE_THRESHOLD = 30
SESSION_BACKEND = os.environ.get("PLANNER_SESSION_BACKEND", "screen")
JIRA_SYNC_INTERVAL = 1800
