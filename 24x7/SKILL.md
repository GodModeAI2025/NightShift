---
name: 24x7
license: Apache License Version 2.0
compatibility: "Requires Claude Code CLI (claude -p), bash, python3, jq. macOS recommended for sandbox-exec. timeout command required."
description: "Generates an endless Claude Code runner with inbox/outbox folder architecture as ZIP. Claude processes tasks from an inbox folder, delivers results to an outbox folder, and runs idle tasks when the queue is empty. Use this skill whenever someone wants a permanent Claude agent, a task queue, a job runner, or a drop-folder workflow. Trigger phrases: endloser Runner, 24/7 Claude, Daemon, Always-On, Job-Queue, Inbox Outbox, Drop-Folder, Hot-Folder, Task-Warteschlange, Claude als Service, dauerhaft laufen lassen."
---

# Claude 24x7 — Endless Runner with Inbox/Outbox

Generates a setup where Claude Code runs as a daemon: tasks are dropped into an inbox folder, results appear in an outbox folder. When the queue is empty, Claude runs configurable idle tasks. Each task gets a fresh Claude session — no context rot, no compact issues.

## Why this exists

A single long-running Claude session degrades after hours: context rot makes output unreliable, compaction loses critical information, and errors accumulate without a clean slate. The 24x7 runner solves this by separating the daemon (a bash while-loop) from the worker (a fresh `claude -p` per task). The bash loop is immortal; Claude sessions are ephemeral and clean.

## Input

$ARGUMENTS — interpret as:

| Input | Action |
|-------|--------|
| *(empty)* | Interactive: ask for workspace path, idle behavior |
| `[path]` | Set workspace, ask for idle behavior |
| `[path] --idle [cleanup/docs/tests/sleep]` | Generate directly |

## Architecture

```
workspace/
├── inbox/           ← Drop task folders here
│   └── my-task/
│       ├── task.md      ← The assignment
│       └── materials/   ← Input files
├── working/         ← Currently being processed
├── outbox/          ← Completed tasks (output/ + log.md)
├── failed/          ← Failed or timed-out tasks
├── idle/            ← What to do when queue is empty
│   └── idle-tasks.md
├── runner.sh        ← The endless loop
├── watchdog.sh      ← Heartbeat monitor
└── .claude/settings.json  ← Security hooks
```

### The loop

1. Check inbox for oldest task folder containing a task.md
2. Move it to working/
3. Start a fresh `claude -p` session with the task
4. On success → move to outbox/. On failure → move to failed/
5. No tasks? → Run idle task (or sleep)
6. Back to step 1

Every task gets a fresh session. This is the key design decision — it prevents context rot and makes the runner reliable over days and weeks.

## Workflow

### Step 1: Gather input

Ask the user for:
1. **Workspace path** — where the runner lives
2. **Idle behavior** — what Claude does when the inbox is empty: cleanup (tidy workspace, collect TODOs), docs (update documentation), tests (suggest missing tests), or sleep (do nothing, save API costs)
3. **Stack info** (optional) — what kinds of projects will be processed

### Step 2: Explain task.md format

Each task folder in inbox/ needs a task.md:

```markdown
## Task: [Title]
Priorität: [hoch/mittel/niedrig]

### Auftrag
[Concrete instructions — what exactly to do]

### Input
[Which files in materials/ are relevant and what they contain]

### Erwarteter Output
[What should appear in output/ — file names, formats]
```

All work happens inside the task's working directory. Claude reads from materials/, writes to output/, and creates a log.md summary. No access to paths outside the workspace — this is enforced by the sandbox profile, the CLAUDE.md rules, and explicit autonomy zones (green/yellow/red) that define what Claude may do freely, what it must log, and what is forbidden. Error tolerance rules in CLAUDE.md prevent Claude from stopping at trivial issues while ensuring it halts on real failures.

### Step 3: Generate ZIP

Copy and configure the build script:

```bash
cp /mnt/skills/user/24x7/scripts/build_zip.py /home/claude/build_24x7.py
```

Set variables directly in the script OR pass as environment variables:
- `WORKSPACE` — absolute workspace path (or `export CLAUDE_24X7_WORKSPACE=/path`)
- `IDLE_BEHAVIOR` — cleanup, docs, tests, or sleep
- `POLL_INTERVAL` — seconds between inbox checks (default 30)
- `MAX_TASK_MINUTES` — timeout per task (default 60)

```bash
python3 /home/claude/build_24x7.py
```

### Step 4: Present output

1. Present the ZIP with `present_files`
2. Show installation and task-dropping instructions
3. Show cost warning — 24/7 operation generates continuous API calls

## Generated files

| File | Purpose |
|------|---------|
| runner.sh | Endless loop: poll inbox, spawn Claude, route results. PID lock + graceful shutdown. |
| runner-bg.sh | Background starter (nohup wrapper) |
| watchdog.sh | Heartbeat monitor with live status: 📥inbox 🔄working ✅done ❌failed |
| sandbox.sb | macOS sandbox profile — restricts filesystem to workspace + /tmp |
| .claude/settings.json | Hooks: PreToolUse (security), PostToolUse (heartbeat) |
| CLAUDE.md | Workspace rules for Claude: isolation, output conventions, security |
| idle/idle-tasks.md | Configurable idle behavior |
| inbox/beispiel-task/ | Example task with task.md template |
| README.md | Full installation, usage, and configuration guide |

## Error handling

| Situation | Action |
|-----------|--------|
| Runner already running | PID lock detects it, shows existing PID |
| Task without task.md | Folder is skipped, next task is processed |
| Task timeout (default 60 min) | Task moves to failed/ with timeout note in log.md |
| Claude error (exit != 0) | Task moves to failed/ with exit code in log.md |
| SIGTERM / SIGINT | Graceful shutdown: in-progress task moves to failed/, PID file cleaned up |
| Empty inbox + idle=sleep | No Claude call, just sleep. Saves API costs. |

## Security

- All work is confined to the workspace — no external paths allowed
- PreToolUse hook blocks: rm -rf, mkfs, dd, sudo, chmod 777, curl-pipe-bash, eval, fork bombs
- Sandbox profile restricts filesystem to workspace + /tmp at kernel level
- PID lock prevents duplicate runner instances
- Task timeout prevents infinite loops
- **Cost warning:** 24/7 operation generates continuous API calls. Set idle to "sleep" if cost is a concern. Monitor the Anthropic dashboard.
