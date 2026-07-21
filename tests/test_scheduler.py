import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from planner.db import init_db, list_tasks, get_last_run
from planner.scheduler import parse_claude_output, Scheduler, RecurringTask


def test_parse_claude_output_tasks():
    output = """
SUMMARY: 3 new errors in #issues channel.

TASKS:
- Investigate WEBAPP-NW spike (today, priority 2)
- Check PLEX-DB connection errors (today, priority 3)
- Review monitoring alert rule (this_week, priority 4)
"""
    tasks = parse_claude_output(output)
    assert len(tasks) == 3
    assert tasks[0]["title"] == "Investigate WEBAPP-NW spike"
    assert tasks[0]["horizon"] == "today"
    assert tasks[0]["priority"] == 2


def test_parse_claude_output_empty():
    tasks = parse_claude_output("No new issues found.")
    assert tasks == []


def test_should_run_today_no_prior_run(tmp_path):
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    sched = Scheduler(db_path)
    assert sched.should_run_today("slack") is True


def test_should_run_today_already_ran(tmp_path):
    from planner.db import set_last_run
    import datetime
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    today = datetime.datetime.now().isoformat()
    set_last_run(db_path, "slack", today)
    sched = Scheduler(db_path)
    assert sched.should_run_today("slack") is False


def test_should_run_daily_time_gate(tmp_path):
    import datetime
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    sched = Scheduler(db_path)
    task = RecurringTask(name="t", label="T", prompt="p", frequency="daily", time="09:00")
    before = datetime.datetime(2026, 7, 1, 8, 30)  # before 09:00
    after = datetime.datetime(2026, 7, 1, 9, 5)    # after 09:00
    assert sched.should_run(task, now=before) is False
    assert sched.should_run(task, now=after) is True


def test_should_run_daily_weekday_filter(tmp_path):
    import datetime
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    sched = Scheduler(db_path)
    task = RecurringTask(name="t", label="T", prompt="p", frequency="daily", days=["mon", "wed", "fri"])
    monday = datetime.datetime(2026, 6, 29, 9, 0)   # Monday
    tuesday = datetime.datetime(2026, 6, 30, 9, 0)  # Tuesday
    assert sched.should_run(task, now=monday) is True
    assert sched.should_run(task, now=tuesday) is False


def test_should_run_interval(tmp_path):
    import datetime
    from planner.db import set_last_run
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    sched = Scheduler(db_path)
    task = RecurringTask(name="t", label="T", prompt="p", frequency="interval", interval_hours=4)
    base = datetime.datetime(2026, 7, 1, 10, 0)
    set_last_run(db_path, "t", base.isoformat())
    too_soon = datetime.datetime(2026, 7, 1, 13, 0)   # 3h later
    ready = datetime.datetime(2026, 7, 1, 14, 1)       # 4h+ later
    assert sched.should_run(task, now=too_soon) is False
    assert sched.should_run(task, now=ready) is True


def test_should_run_weekly(tmp_path):
    import datetime
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    sched = Scheduler(db_path)
    task = RecurringTask(name="t", label="T", prompt="p", frequency="weekly", day="mon")
    monday = datetime.datetime(2026, 6, 29, 9, 0)   # Monday
    tuesday = datetime.datetime(2026, 6, 30, 9, 0)  # Tuesday
    assert sched.should_run(task, now=monday) is True
    assert sched.should_run(task, now=tuesday) is False


def test_run_task_records_last_run(tmp_path):
    from planner.db import add_task
    db_path = tmp_path / "tasks.db"
    init_db(db_path)
    add_task(db_path, source="slack", title="Slack Digest", description="check slack")
    sched = Scheduler(db_path)
    task = RecurringTask(name="slack", label="Slack Digest", prompt="check slack")
    with patch("planner.session_manager.run_recurring_via_session") as mock_rr:
        sched.run_task(task)
    mock_rr.assert_called_once()
    assert get_last_run(db_path, "slack") is not None
