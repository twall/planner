import datetime
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from planner.config import DB_PATH, TASKS_CONFIG_PATH
from planner.db import add_task, get_last_run, set_last_run

RECURRING_SOURCES = {"slack", "git", "sentry"}


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
    auto_submit: bool = False         # submit prompt automatically (vs. populate only)


def load_tasks(config_path: Path = TASKS_CONFIG_PATH) -> list[RecurringTask]:
    """Load recurring task definitions from tasks.json (import/seed only)."""
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
            auto_submit=bool(item.get("auto_submit", False)),
        ))
    return tasks


def import_tasks_to_db(db_path: Path, config_path: Path = TASKS_CONFIG_PATH) -> None:
    """Hydrate recurring task DB rows from tasks.json. Idempotent — only updates schedule fields."""
    from planner.db import list_tasks, update_task
    if not config_path.exists():
        return
    json_tasks = load_tasks(config_path)
    db_tasks = {t["source"]: t for t in list_tasks(db_path) if t["source"] in RECURRING_SOURCES}
    for rt in json_tasks:
        if rt.name not in db_tasks:
            continue
        task = db_tasks[rt.name]
        # Only import if DB fields are still blank (don't overwrite user edits)
        needs_import = not task.get("rt_frequency")
        if needs_import:
            update_task(db_path, task["id"],
                        rt_frequency=rt.frequency,
                        rt_time=rt.time,
                        rt_days=",".join(rt.days) if rt.days else None,
                        rt_day=rt.day,
                        rt_interval_hours=rt.interval_hours)


def export_tasks_from_db(db_path: Path, config_path: Path = TASKS_CONFIG_PATH) -> None:
    """Write recurring task schedule fields from DB back to tasks.json."""
    from planner.db import list_tasks
    if not config_path.exists():
        return
    with open(config_path) as f:
        data = json.load(f)
    db_tasks = {t["source"]: t for t in list_tasks(db_path) if t["source"] in RECURRING_SOURCES}
    for rt in data.get("recurring_tasks", []):
        task = db_tasks.get(rt["name"])
        if not task:
            continue
        if task.get("rt_frequency"):
            rt["frequency"] = task["rt_frequency"]
        if task.get("rt_time") is not None:
            rt["time"] = task["rt_time"]
        days_str = task.get("rt_days")
        rt["days"] = days_str.split(",") if days_str else []
        if task.get("rt_day") is not None:
            rt["day"] = task["rt_day"]
        if task.get("rt_interval_hours") is not None:
            rt["interval_hours"] = task["rt_interval_hours"]
        if task.get("cwd"):
            rt["cwd"] = task["cwd"]
    with open(config_path, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


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
        """Load recurring tasks from DB (authoritative), falling back to tasks.json for prompt/label."""
        from planner.db import list_tasks
        # Build prompt/label map from tasks.json (these aren't stored in the DB task row)
        json_map = {rt.name: rt for rt in load_tasks(self._config_path)}
        db_tasks = [t for t in list_tasks(self._db_path)
                    if t["source"] in RECURRING_SOURCES and t["status"] != "done"]
        result = []
        for t in db_tasks:
            base = json_map.get(t["source"])
            if base is None:
                continue
            days_str = t.get("rt_days") or ""
            raw_cwd = t.get("cwd") or base.cwd
            result.append(RecurringTask(
                name=t["source"],
                label=t.get("title") or base.label,
                prompt=t.get("description") or base.prompt,
                frequency=t.get("rt_frequency") or base.frequency,
                time=t.get("rt_time") or base.time,
                days=[d for d in days_str.split(",") if d] if days_str else base.days,
                day=t.get("rt_day") or base.day,
                interval_hours=t.get("rt_interval_hours") or base.interval_hours,
                cwd=str(Path(raw_cwd).expanduser()) if raw_cwd else None,
                auto_submit=base.auto_submit,
            ))
        return result

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

    def _invoke_claude(self, prompt: str, cwd: str | None = None,
                       timeout: int = 600) -> str | None:
        try:
            result = subprocess.run(
                ["claude", "--print", prompt],
                capture_output=True, text=True, timeout=timeout,
                cwd=cwd or None,
            )
        except subprocess.TimeoutExpired:
            return None
        if result.returncode != 0:
            return None
        return result.stdout

    def run_task(self, task: RecurringTask) -> list[dict]:
        from planner.db import list_tasks
        from planner.session_manager import run_recurring_via_session
        db_tasks = {t["source"]: t for t in list_tasks(self._db_path)
                    if t["source"] in RECURRING_SOURCES}
        task_dict = db_tasks.get(task.name)
        if task_dict:
            run_recurring_via_session(self._db_path, task_dict, task.prompt,
                                      auto_submit=task.auto_submit)
        else:
            self._invoke_claude(task.prompt, cwd=task.cwd)
        set_last_run(self._db_path, task.name, datetime.datetime.now().isoformat())
        return []

    def run_all_due(self) -> None:
        now = datetime.datetime.now()
        for task in self.load_tasks():
            if self.should_run(task, now):
                self.run_task(task)
