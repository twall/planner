# Ideas

- Allow different task-tracking backends (obsidian, JIRA, asana, etc)
- "Caveman mode" option per task: brevify the description before sending to Claude session (reduce token waste on verbose prompts)

---

## Competitive Analysis — 2026-07-04

Sources: Crystl.dev, Agentastic, AgentOS, Conductor, agent-deck

### Tools surveyed

| Tool | Form | Core differentiator |
|------|------|---------------------|
| **Crystl.dev** | macOS terminal app (closed, $85/yr) | Gems/shards with git worktree isolation; floating Action Panels for approvals; agent-callable CLI to spawn sub-agents |
| **Agentastic** | macOS native app (free) | Kanban board; 34+ agent types; built-in browser + diff viewer; worktree/Docker isolation; Linear integration |
| **AgentOS** (stoic-agentos) | Python SDK + React web (open) | Persistent agent identity with heartbeat liveness; cross-session knowledge base (decisions, notes, patterns) |
| **Conductor** (lovemoon-ai) | Go binary + Next.js web (open, 5★) | Execution-local daemon streams events to remote control plane; task claim/lock prevents double-scheduling |
| **agent-deck** (asheshgoplani) | Go + Bubble Tea TUI + SQLite (MIT, 427★) | Four session states; 30s soft-delete/undo; session fork with history; cost tracking + budget limits; Conductor sub-agent layer |

### What planner does that none of these do

- Monitors **existing** screen/tmux sessions rather than launching sandboxed new ones
- Recurring scheduled tasks with prompt injection
- Works with any CLI agent — not locked to tools the dashboard knows how to launch
- Keyboard-driven TUI, works over SSH, no mouse required

### Ideas worth stealing

**High value**

- **Attention queue** (Crystl, agent-deck) — every tool surfaces NEEDS PERMISSION prominently. Planner buries it as a dot in the task list. Add a persistent status-bar slot or top strip counting blocked sessions.
- **State detection via JSONL** — tail `~/.claude/projects/**/*.jsonl` instead of regex on screen capture output. `tool_use` at tail = ACTIVE; stale mtime after `tool_use` = NEEDS PERMISSION; `turn_duration` event = IDLE. More reliable, backend-agnostic.
- **ERROR state** (agent-deck) — distinct from IDLE; claude exited non-zero. Red `✕`. Planner currently can't distinguish clean finish from crash.
- **30-second soft-delete / archive** (agent-deck) — mark-done is currently permanent. Archive with undo window preserves metadata.

**Medium value**

- **Session fork** (agent-deck) — spawn new session inheriting parent conversation history + worktree. Useful for "retry with fresh start but same context".
- **Claim/lock for recurring tasks** (Conductor) — `locked_until` timestamp on `recurring_runs` prevents double-scheduling on restart.
- **Cost tracking per session** (agent-deck) — token usage + budget limits per recurring task. Prevents runaway spend on unattended tasks.
- **Cross-session knowledge base** (AgentOS) — capture `progress`, `decision`, `blocked`, `pattern` events into SQLite; inject as context at next session start.
- **WORKBENCH.md export** (Crystl) — `planner export --md` dumps open tasks as markdown checklist for agent consumption. `tasks.json` does this partially but isn't agent-friendly.
- **Session registration shell wrapper** (AgentOS) — shell function wrapping `screen -S <name> claude` that registers/deregisters in SQLite on start/exit, replacing `screen -ls` polling.

**Lower priority**

- **Agent personas / CLAUDE.md stubs** (Crystl) — recurring tasks map to named personas with canonical CLAUDE.md stubs in `~/.planner/personas/`.
- **Remote read-only web view** (Conductor) — `planner serve` on localhost:8080, SQLite stays local.
- **In-progress kanban column** (Agentastic) — explicit running/queued/done axis separate from today/this_week horizon.

### State vocabulary consensus

| Planner now | Ecosystem standard | Indicator |
|---|---|---|
| ACTIVE | Running / Processing | `●` green |
| NEEDS PERMISSION | Waiting / Awaiting | `◐` yellow |
| IDLE | Idle / Ready | `○` gray |
| *(missing)* | Error | `✕` red |

### Reference
- agent-deck source: https://github.com/asheshgoplani/agent-deck
