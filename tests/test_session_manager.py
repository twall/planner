import uuid
from unittest.mock import patch

from planner.db import init_db, add_task, list_tasks, update_task
from planner.session_manager import SESSION_NAME_PREFIX, session_name_for, import_orphan_sessions


def test_session_name_for():
    assert session_name_for(42) == "planner-42"


def test_db_stores_claude_session_id(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    tid = add_task(db, source="freeform", title="Test")
    uid = str(uuid.uuid4())
    update_task(db, tid, claude_session_id=uid, screen_session=session_name_for(tid))
    tasks = list_tasks(db)
    assert tasks[0]["claude_session_id"] == uid
    assert tasks[0]["screen_session"] == session_name_for(tid)


def test_import_orphan_creates_task(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    fake_sessions = [{"pid": "999", "name": "my-session",
                      "full_name": "999.my-session", "attached": False}]
    with patch("planner.session_manager._live_sessions",
               return_value={"999.my-session": fake_sessions[0]}):
        count = import_orphan_sessions(db)
    assert count == 1
    tasks = list_tasks(db)
    assert tasks[0]["title"] == "my-session"
    assert tasks[0]["source"] == "screen"


def test_import_skips_linked_sessions(tmp_path):
    db = tmp_path / "test.db"
    init_db(db)
    # Pre-existing task already linked to the session
    add_task(db, source="freeform", title="Existing", screen_session="999.my-session")
    fake = {"999.my-session": {"pid": "999", "name": "my-session",
                                "full_name": "999.my-session", "attached": False}}
    with patch("planner.session_manager._live_sessions", return_value=fake):
        count = import_orphan_sessions(db)
    assert count == 0
