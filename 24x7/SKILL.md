---
name: 24x7
license: Apache-2.0
compatibility: "Requires Claude Code CLI (claude -p), bash, python3 >= 3.9, jq. Docker Compose for the default isolated run; the image brings timeout with it. Without a container: macOS with sandbox-exec, plus timeout or gtimeout on PATH."
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
├── 24x7-docker.sh   ← Builds the container and starts the runner in it
├── Dockerfile       ← runner + egress proxy
├── docker-compose.yml ← Workspace at /workspace, internal network
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
# scripts/build_zip.py sits next to this SKILL.md: under ~/.claude/skills/
# after installing from the release, under /mnt/skills/user/ on claude.ai.
SKILL_DIR="$HOME/.claude/skills/24x7"
[ -d "$SKILL_DIR" ] || SKILL_DIR="/mnt/skills/user/24x7"
cp "$SKILL_DIR/scripts/build_zip.py" ~/build_24x7.py
```

Set variables directly in the script OR pass as environment variables:
- `WORKSPACE` — absolute workspace path (or `export CLAUDE_24X7_WORKSPACE=/path`)
- `IDLE_BEHAVIOR` — cleanup, docs, tests, or sleep
- `POLL_INTERVAL` — seconds between inbox checks (default 30)
- `MAX_TASK_MINUTES` — timeout per task (default 60)
- `CLAUDE_24X7_OUT` — where the ZIP is written. The default `/mnt/user-data/outputs/24x7-setup.zip` exists on claude.ai only; everywhere else set it, e.g. `CLAUDE_24X7_OUT=~/24x7-setup.zip python3 ~/build_24x7.py`

```bash
python3 ~/build_24x7.py
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
| 24x7-docker.sh | Builds the container and starts the runner in it. `--logs` follows the log. |
| Dockerfile | Two targets: runner (Claude Code) and egress (allowlist proxy) |
| docker-compose.yml | Workspace at /workspace, internal network, read-only root, all capabilities dropped |
| watchdog.sh | Heartbeat monitor with live status: 📥inbox 🔄working ✅done ❌failed. CLAUDE_24X7_WATCHDOG_AKTION picks the reaction: melden (default), beenden, neustart. Only for a run on the host: in the container the heartbeat lands in its own tmpfs. |
| sandbox.sb | macOS sandbox profile: restricts writes to workspace + /tmp. Reads outside the workspace and outbound traffic on 443 stay open. |
| .claude/settings.json | Hooks: PreToolUse (security), PostToolUse (heartbeat) |
| CLAUDE.md | Workspace rules: isolation, autonomy zones, error tolerance, workspace memory |
| idle/idle-tasks.md | Configurable idle behavior |
| inbox/beispiel-task/ | Example task with task.md template |
| README.md | Full installation, usage, and configuration guide |

## Workspace Memory (decisions.md)

Each task runs in a fresh Claude session — no shared context. But decisions made in one task often matter for later tasks (e.g., "we chose PostgreSQL over SQLite" or "API naming follows camelCase"). The runner instructs Claude to read `decisions.md` from the workspace root at the start of each task, and append relevant decisions at the end. This gives cross-task persistence without a long-lived session.

Format: date, task name, decision, reasoning. Append-only.

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

- CLAUDE.md demands "never read or write paths outside the workspace". The write half of that is enforced by a PreToolUse hook: a Write, Edit, MultiEdit or NotebookEdit outside the workspace ends with exit 2. The read half stays a rule in CLAUDE.md, and so does a write that a Bash command performs.
- PreToolUse hook blocks a fixed list of command patterns: rm against dangerous targets (root, home and its direct children, globs, parent paths, .git, system directories), mkfs, dd writing to a device, sudo, chmod 777, curl piped into bash, eval. Fork bombs are not on that list, there is no pattern for them.
- Two PreToolUse entries, one implementation for both skills in `gemeinsam.py`. `"matcher": "Bash"` greps the command text; `"matcher": "Write|Edit|MultiEdit|NotebookEdit"` resolves the target path and blocks every write outside the workspace (`CLAUDE_24X7_WORKSPACE`), plus `.claude/settings.json` inside it. Without jq both block instead of waving the call through.
- The path barrier resolves symlinks on both sides before comparing, so a link out of the workspace is blocked. What it does not see: a write performed by a Bash command (`echo >`, `tee`, `cp`, `mv`), any read, tools contributed by MCP servers, and a link created between the check and the write. It is a barrier for the four write tools, not a boundary for the run. See [SECURITY.md](../SECURITY.md).
- The container is the default fence: only the workspace is mounted, the home directory lives in a volume, and the sole route outward is a proxy that allows api.anthropic.com and answers everything else with 403. The image also brings `timeout`, which the task cap needs and a stock macOS does not have.
- The runner measures which of the two it sits behind and aborts with exit code 3 when it finds neither. It is a probe, not a declaration: container markers for the first, an unreadable `/Users` for the second. `CLAUDE_24X7_SANDBOXED` is a cross-check only and unlocks nothing. `CLAUDE_24X7_ALLOW_UNSANDBOXED=1` is the documented way out; tell the user what it costs.
- Sandbox profile restricts writes to workspace + /tmp at kernel level. Reads outside the workspace and outbound network traffic are not restricted. It is the macOS option, not the default.
- PID lock prevents duplicate runner instances
- Task timeout prevents infinite loops
- **Cost:** 24/7 operation generates continuous API calls, idle included: with any idle behaviour but `sleep`, Claude works for up to the idle timeout and then pauses only for the poll interval. `CLAUDE_24X7_BUDGET_USD` (default 50.00) and `CLAUDE_24X7_BUDGET_TOKENS` bound the whole run; at the limit the running task goes to `failed/` and the daemon exits 9. The running total is `24x7-kosten.json` in the workspace root, each task gets a `receipt.md` next to its output. The figure is an estimate from a dated price table, so keep watching the Anthropic dashboard.
