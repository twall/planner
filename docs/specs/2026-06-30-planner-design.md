# Planner — Design Spec
**Date:** 2026-06-30
**Status:** Approved

## Overview

A persistent terminal dashboard for daily/weekly task planning and Claude Code session monitoring. Runs in a dedicated `screen` session (`master`), always on. Built with Python + Textual. Tasks sourced from JIRA and freeform input; screen sessions polled for idle/permission-wait states.

---

## Architecture

```
~/planner/
├── planner/
│   ├── app.py               # Textual app entry point
│   ├── db.py                # SQLite via aiosqlite
│   ├── jira.py              # JIRA REST client
│   ├── screen_monitor.py    # screen session poller
│   ├── scheduler.py         # recurring task scheduler
│   ├── cli.py               # CLI entry point (used by /task skill)
│   ├── config.py            # paths, intervals, JIRA project keys
│   └── widgets/
│       ├── session_panel.py
│       ├── task_panel.py
│       ├── briefing_panel.py
│       └── status_bar.py
├── data/
│   └── tasks.db             # SQLite — freeform tasks + JIRA cache + briefing results
├── skills/
│   └── task.md              # /task Claude Code skill (installed globally)
├── scripts/
│   └── planner              # shell wrapper: activates venv + launches Textual app
├── requirements.txt
└── README.md
```

**Data flow:**
- `screen_monitor.py` polls every 5s — detects session state changes
- JIRA synced on startup + `j` key
- Recurring tasks (Slack, Bitbucket) run on startup if not yet run today; re-triggered manually
- SQLite is the single source of truth; dashboard works offline
- `/task` skill in any Claude session writes to `tasks.db` via `python -m planner.cli`

---

## Screen Session Monitor

**Poll cycle (every 5s):**
1. `screen -ls` — parse pid, name, attached/detached state
2. Per session: `screen -S <pid>.<name> -X hardcopy -h /tmp/planner-<pid>.txt` — capture scrollback
3. Diff last N lines against previous snapshot:
   - Unchanged > 30s → **IDLE**
   - Changed → **ACTIVE**
4. Regex scan last 50 lines for prompt patterns:
   - `\[Y/n\]`, `\[y/N\]`, `\(y/n\)` → **NEEDS INPUT**
   - `Allow|Deny|Yes|No.*\?` in dialog context → **NEEDS PERMISSION**
   - `Do you want to` → **NEEDS PERMISSION**
5. Session states: `ACTIVE` | `IDLE` | `NEEDS INPUT` | `NEEDS PERMISSION` | `ATTACHED`

**Session panel interactions:**
- `enter` — attach to session (`screen -r <session>`)
- `p` — popup showing last 20 lines of session hardcopy

---

## Task Management

### Data Model (SQLite)

```sql
CREATE TABLE tasks (
    id          INTEGER PRIMARY KEY,
    source      TEXT NOT NULL,     -- 'freeform' | 'jira' | 'slack' | 'bitbucket'
    jira_key    TEXT,
    title       TEXT NOT NULL,
    description TEXT,
    priority    INTEGER DEFAULT 3, -- 1 (highest) to 5 (lowest)
    horizon     TEXT DEFAULT 'backlog', -- 'today' | 'this_week' | 'backlog'
    status      TEXT DEFAULT 'open',    -- 'open' | 'in_progress' | 'done'
    screen_session TEXT,           -- linked screen session name (nullable)
    created_at  TEXT,
    updated_at  TEXT,
    jira_synced_at TEXT
);
```

### JIRA Sync
- Fetches open issues assigned to user across configured project keys (default: `PLEX`)
- Upserts on `jira_key`; freeform tasks never overwritten
- JIRA status (done/closed) reflected on next sync
- Triggered: startup + `j` key

### Horizons
- **Today** — committed for today
- **This Week** — planned this week
- **Backlog** — unscheduled

### `/task` Skill
Global Claude Code skill installed to `~/.claude/skills/task.md`. Writes to `tasks.db` via `python -m planner.cli`.

```
/task add "title" [--today|--week|--backlog] [--priority 1-5]
/task list
```

---

## Recurring Daily Tasks

Run on dashboard startup if `last_run_date < today`. Re-triggered manually per-source or all at once.

### 1. Slack Digest (`#issues` + `#monitoring`)
- Uses `slack:channel-digest` skill / Slack MCP
- Reads unread messages since last check
- Produces: error/alert summary + actionable TODO items
- TODO items inserted into tasks table with `source='slack'`, horizon `today`

### 2. Bitbucket PR Review
- Uses `review-bitbucket-prs` skill (`~/plex/search/ops/claude/skills/review-bitbucket-prs/`)
- Checks repos: `rd`, `plex-search`, `plex-search-ui`
- Produces: grouped action list (approve / respond / first review)
- Action items inserted with `source='bitbucket'`, `[BB]` tag, horizon `today`

### 3. Sentry Gap Check
- Queries Sentry REST API for recent issues across `WEBAPP`, `REST-API`, `internal` projects
- Cross-references against issues already surfaced in `#issues` / `#monitoring` Slack digest
- Reports only issues **not** seen in Slack — i.e. dropouts from automated alerting pipeline
- Produces: list of unnotified issues with severity + link; inserted as `source='sentry'` tasks
- Uses `analyze-issues` skill / Sentry MCP + Slack MCP for cross-reference
- Keybinding: included in `R` (re-run all); no dedicated single key (lower urgency)

**Execution:** Each recurring task spawns a background `claude -p "<prompt>"` subprocess using the relevant skill, captures output, parses into summary + TODO items, stores in DB.

**Schedule:**
- Auto-run on startup if not yet run today
- `s` — re-run Slack digest
- `b` — re-run Bitbucket PR review
- `R` — re-run all recurring tasks

---

## Dashboard Layout

```
┌─────────────────────────────────────────────────────────────────┐
│  PLANNER  [Mon Jun 30]  [last sync: 2m ago]  [next: 28m]  09:42 │
├───────────────────────┬─────────────────────────────────────────┤
│ Claude Sessions  (16) │ Tasks          [ today | week | backlog ]│
│───────────────────────│─────────────────────────────────────────│
│ ● webapp   NEEDS PERM │ TODAY                                    │
│ ● imap     ACTIVE     │  1. [PLEX-4068] Compound fragmentation  │
│ ● jobs     IDLE  8m   │  2. [BB] Review: plex-search PR #42     │
│ ● agent-c  ACTIVE     │  3. [SLACK] WEBAPP-NW spike — check     │
│ ● sentry   IDLE  22m  │                                          │
│ ● ...      ...        │ THIS WEEK                                │
│                       │  4. [PLEX-4071] Vector prompt tuning     │
│                       │  5. [freeform] imap graph perf review   │
│                       │                                          │
│ [enter] attach        │ BACKLOG                                  │
│ [p] preview output    │  6. [WEBAPP-NW] SSE grace window fix    │
├───────────────────────┴─────────────────────────────────────────┤
│ Daily Briefing                                           [x] hide│
│  Slack: 3 new errors in #issues — WEBAPP-NW x2, PLEX-DB x1      │
│  PRs: 2 need response (plex-search #38, #42), 1 to approve      │
└─────────────────────────────────────────────────────────────────┘
```

## Keybindings

| Key | Action |
|-----|--------|
| `tab` | Switch focus: sessions ↔ tasks |
| `enter` | Attach to selected screen session |
| `p` | Preview last 20 lines of session output |
| `n` | New freeform task |
| `e` | Edit selected task |
| `d` | Mark task done |
| `m` | Move task horizon (today → week → backlog → today) |
| `j` | Sync JIRA |
| `b` | Re-run Bitbucket PR review |
| `s` | Re-run Slack digest |
| `R` | Re-run all recurring tasks |
| `P` | Enter planning mode (morning triage) — v2, not in initial implementation |
| `q` | Quit |

---

## Configuration (`config.py`)

```python
JIRA_PROJECTS = ["PLEX"]
SENTRY_PROJECTS = ["WEBAPP", "REST-API", "internal"]
SCREEN_POLL_INTERVAL = 5        # seconds
SCREEN_IDLE_THRESHOLD = 30      # seconds before IDLE state
JIRA_SYNC_INTERVAL = 1800       # 30 minutes auto-sync
RECURRING_TASK_HOUR = 8         # auto-run daily briefing at 8am if missed
BITBUCKET_REPOS = ["rd", "plex-search", "plex-search-ui"]
SLACK_CHANNELS = ["#issues", "#monitoring"]
DB_PATH = "~/planner/data/tasks.db"
SKILLS_PATH = "~/plex/search/ops/claude/skills"
```

---

## GitHub

Private repo: `github.com/twall/planner`
Local: `~/planner`
