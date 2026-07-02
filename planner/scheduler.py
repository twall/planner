import datetime
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from planner.config import DB_PATH, TASKS_CONFIG_PATH
from planner.db import add_task, get_last_run, set_last_run


TASK_LINE_RE = re.compile(
    r'^-\s+(.+?)\s+\((\w+),\s*priority\s*(\d)\)',
    re.IGNORECASE
)

DAY_NAMES = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


@dataclass
class RecurringTask:
    name: str
    label: str
    prompt: str
    # Schedule fields — all optional, defaults to "daily, any time"
    frequency: str = "daily"          # "daily" | "weekly" | "interval"
    time: Optional[str] = None        # "HH:MM" — earliest wall-clock time to run
    days: list = field(default_factory=list)  # ["mon","tue",...] — limit to these weekdays
    day: Optional[str] = None         # for frequency="weekly": which weekday
    interval_hours: Optional[float] = None    # for frequency="interval"
    cwd: Optional[str] = None         # working directory for claude invocation


def load_tasks(config_path: Path = TASKS_CONFIG_PATH) -> list[RecurringTask]:
    if not config_path.exists():
        return []
    with open(config_path) as f:
        data = json.load(f)
    tasks = []
    for item in data.get("recurring_tasks", []):
        raw_cwd = item.get("cwd")
        tasks.append(RecurringTask(
            name=item["name"],
            label=item["label"],
            prompt=item["prompt"],
            frequency=item.get("frequency", "daily"),
            time=item.get("time"),
            days=item.get("days", []),
            day=item.get("day"),
            interval_hours=item.get("interval_hours"),
            cwd=str(Path(raw_cwd).expanduser()) if raw_cwd else None,
        ))
    return tasks


def load_jira_sync_interval(config_path: Path = TASKS_CONFIG_PATH) -> int:
    if not config_path.exists():
        from planner.config import JIRA_SYNC_INTERVAL
        return JIRA_SYNC_INTERVAL
    with open(config_path) as f:
        data = json.load(f)
    from planner.config import JIRA_SYNC_INTERVAL
    return data.get("jira_sync_interval_seconds", JIRA_SYNC_INTERVAL)


def parse_claude_output(output: str) -> list[dict]:
    tasks = []
    in_tasks = False
    for line in output.splitlines():
        if line.strip().upper().startswith("TASKS:"):
            in_tasks = True
            continue
        if in_tasks:
            m = TASK_LINE_RE.match(line.strip())
            if m:
                tasks.append({
                    "title": m.group(1).strip(),
                    "horizon": m.group(2).lower(),
                    "priority": int(m.group(3)),
                    "description": None,
                })
    return tasks


def _parse_time(time_str: str) -> tuple[int, int]:
    """Parse "HH:MM" → (hour, minute)."""
    h, m = time_str.split(":")
    return int(h), int(m)


class Scheduler:
    def __init__(self, db_path: Path = DB_PATH, config_path: Path = TASKS_CONFIG_PATH):
        self._db_path = db_path
        self._config_path = config_path

    def load_tasks(self) -> list[RecurringTask]:
        return load_tasks(self._config_path)

    def should_run(self, task: RecurringTask, now: Optional[datetime.datetime] = None) -> bool:
        if now is None:
            now = datetime.datetime.now()

        # Check time-of-day gate
        if task.time:
            h, m = _parse_time(task.time)
            if (now.hour, now.minute) < (h, m):
                return False

        last_run_str = get_last_run(self._db_path, task.name)

        if task.frequency == "interval":
            hours = task.interval_hours or 24
            if last_run_str is None:
                return True
            last_run = datetime.datetime.fromisoformat(last_run_str)
            return (now - last_run).total_seconds() >= hours * 3600

        if task.frequency == "weekly":
            target_day = DAY_NAMES.get((task.day or "mon").lower(), 0)
            if now.weekday() != target_day:
                return False
            if last_run_str is None:
                return True
            last_run = datetime.datetime.fromisoformat(last_run_str)
            return last_run.date() < now.date()

        # frequency == "daily" (default)
        if task.days:
            allowed = {DAY_NAMES[d.lower()] for d in task.days if d.lower() in DAY_NAMES}
            if now.weekday() not in allowed:
                return False
        if last_run_str is None:
            return True
        last_run = datetime.datetime.fromisoformat(last_run_str)
        return last_run.date() < now.date()

    # Keep backward-compat name used in tests and app
    def should_run_today(self, task_name: str) -> bool:
        tasks = self.load_tasks()
        task = next((t for t in tasks if t.name == task_name), None)
        if task is None:
            today = datetime.date.today().isoformat()
            return get_last_run(self._db_path, task_name) != today
        return self.should_run(task)

    def _invoke_claude(self, prompt: str, cwd: str | None = None) -> str | None:
        result = subprocess.run(
            ["claude", "--print", prompt],
            capture_output=True, text=True, timeout=120,
            cwd=cwd or None,
        )
        if result.returncode != 0:
            return None
        return result.stdout

    def run_task(self, task: RecurringTask) -> list[dict]:
        output = self._invoke_claude(task.prompt, cwd=task.cwd)
        if output is None:
            return []
        parsed = parse_claude_output(output)
        for item in parsed:
            add_task(
                self._db_path,
                source=task.name,
                title=item["title"],
                horizon=item.get("horizon", "today"),
                priority=item.get("priority", 3),
                description=item.get("description"),
            )
        set_last_run(self._db_path, task.name, datetime.datetime.now().isoformat())
        return parsed

    def run_all_due(self) -> None:
        now = datetime.datetime.now()
        for task in self.load_tasks():
            if self.should_run(task, now):
                self.run_task(task)
