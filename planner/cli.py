import json
import sys
from pathlib import Path
from planner.config import DB_PATH
from planner.db import init_db, add_task, list_tasks

INBOX_PATH = Path.home() / ".planner" / "inbox.json"


HELP = """\
Usage: planner.cli <command> [options]

Commands:
  add <title> [--today|--week|--backlog] [--priority 1-5]
      Add a new task.

  list
      List all open tasks with id, source, title, horizon, and priority.

  update <id> [options]
      Update an existing task by id (from `list`).
      --today | --week | --backlog   Change horizon
      --priority N                   Change priority (1=urgent, 5=low)
      --title "..."                  Rename the task
      --desc "..."                   Set the description/prompt

  inbox add <title|json> [--today|--week|--backlog] [--desc "..."]
      Queue a task to ~/.planner/inbox.json (picked up on next planner launch).
      Accepts a plain title with flags or a raw JSON object.

Options:
  -h, --help    Show this help message.
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args or args[0] in ("-h", "--help"):
        print(HELP)
        return 0

    command = args[0]
    rest = args[1:]

    init_db(DB_PATH)

    if command == "add":
        if not rest or rest[0].startswith("--"):
            print("Error: title required", file=sys.stderr)
            return 1
        title = rest[0]
        horizon = "backlog"
        priority = 3
        i = 1
        while i < len(rest):
            if rest[i] == "--today":
                horizon = "today"
            elif rest[i] == "--week":
                horizon = "this_week"
            elif rest[i] == "--backlog":
                horizon = "backlog"
            elif rest[i] == "--priority" and i + 1 < len(rest):
                try:
                    priority = int(rest[i + 1])
                    i += 1
                except ValueError:
                    pass
            i += 1
        task_id = add_task(DB_PATH, source="freeform", title=title, horizon=horizon, priority=priority)
        print(f"Added task #{task_id}: {title} [{horizon}]")
        return 0

    elif command == "list":
        tasks = list_tasks(DB_PATH)
        if not tasks:
            print("No tasks.")
            return 0
        for t in tasks:
            tag = f"[{t['jira_key']}]" if t.get("jira_key") else f"[{t['source']}]"
            print(f"  {t['id']:3}. {tag} {t['title']}  ({t['horizon']}, p{t['priority']})")
        return 0

    elif command == "inbox":
        # inbox add '{"title": "...", "description": "...", "horizon": "this_week"}'
        # inbox add title [--desc "..."] [--today|--week|--backlog]
        if not rest:
            print("Usage: planner.cli inbox add <title|json> [--desc ...] [--today|--week|--backlog]", file=sys.stderr)
            return 1
        if rest[0] == "add":
            rest = rest[1:]
        if not rest:
            print("Error: title or JSON required", file=sys.stderr)
            return 1
        # Accept a raw JSON object or a plain title with flags
        if rest[0].startswith("{"):
            try:
                entry = json.loads(" ".join(rest))
            except json.JSONDecodeError as e:
                print(f"Error: invalid JSON: {e}", file=sys.stderr)
                return 1
        else:
            title = rest[0]
            horizon = "this_week"
            description = None
            i = 1
            while i < len(rest):
                if rest[i] == "--today":
                    horizon = "today"
                elif rest[i] == "--week":
                    horizon = "this_week"
                elif rest[i] == "--backlog":
                    horizon = "backlog"
                elif rest[i] in ("--desc", "--description") and i + 1 < len(rest):
                    description = rest[i + 1]
                    i += 1
                i += 1
            entry = {"title": title, "horizon": horizon}
            if description:
                entry["description"] = description
        INBOX_PATH.parent.mkdir(parents=True, exist_ok=True)
        existing = []
        if INBOX_PATH.exists():
            try:
                existing = json.loads(INBOX_PATH.read_text())
            except Exception:
                existing = []
        existing.append(entry)
        INBOX_PATH.write_text(json.dumps(existing, indent=2))
        print(f"Queued: {entry['title']} [{entry.get('horizon', 'this_week')}]")
        return 0

    elif command == "update":
        # update <id> [--today|--week|--backlog] [--priority N] [--title "..."] [--desc "..."]
        from planner.db import update_task
        if not rest:
            print("Usage: planner.cli update <id> [--today|--week|--backlog] [--priority N] [--title ...] [--desc ...]",
                  file=sys.stderr)
            return 1
        try:
            task_id = int(rest[0])
        except ValueError:
            print(f"Error: id must be an integer, got {rest[0]!r}", file=sys.stderr)
            return 1
        fields: dict = {}
        i = 1
        while i < len(rest):
            if rest[i] == "--today":
                fields["horizon"] = "today"
            elif rest[i] == "--week":
                fields["horizon"] = "this_week"
            elif rest[i] == "--backlog":
                fields["horizon"] = "backlog"
            elif rest[i] == "--priority" and i + 1 < len(rest):
                try:
                    fields["priority"] = int(rest[i + 1])
                    i += 1
                except ValueError:
                    pass
            elif rest[i] == "--title" and i + 1 < len(rest):
                fields["title"] = rest[i + 1]
                i += 1
            elif rest[i] in ("--desc", "--description") and i + 1 < len(rest):
                fields["description"] = rest[i + 1]
                i += 1
            i += 1
        if not fields:
            print("Error: no fields to update", file=sys.stderr)
            return 1
        update_task(DB_PATH, task_id, **fields)
        changes = ", ".join(f"{k}={v!r}" for k, v in fields.items())
        print(f"Updated task #{task_id}: {changes}")
        return 0

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
