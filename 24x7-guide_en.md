# 24x7 — Training Guide

> An endless Claude Code runner with inbox/outbox task queue.

**Skill Repository:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Landing Page:** [godmodeai2025.github.io/NightShift](https://godmodeai2025.github.io/NightShift/)

---

## What You Will Learn

After this guide, you will be able to:

1. Install the 24x7 skill into Claude Code
2. Set up an endless runner with inbox/outbox architecture
3. Drop tasks as folders and collect results
4. Configure idle behavior for when the queue is empty
5. Monitor the runner and handle failures

---

## Prerequisites

- [ ] **Claude Code CLI** installed and authenticated
- [ ] **bash**, **python3** (3.9 or newer), and **jq** in your PATH
- [ ] **timeout** or **gtimeout** in your PATH. macOS does not ship `timeout`: `brew install coreutils` provides `gtimeout`. Without either, the runner refuses to start.
- [ ] **macOS** recommended (for sandbox). Linux works without it.
- [ ] A directory for the workspace (no git required, unlike Nightshift)

---

## Lesson 1: Nightshift vs. 24x7 — When to Use Which

**Nightshift** is a sprint: one project, one task, one run, one commit. Use it when you have a specific, planned piece of work.

**24x7** is a daemon: an endless loop that processes tasks from a queue. Use it when:

- You have multiple small tasks throughout the day
- You want to drop work and come back for results later
- You need a persistent worker that's always ready
- Tasks are independent from each other (no shared state between tasks)

The key architectural difference: **Nightshift uses one long Claude session** with compact recovery hooks. **24x7 uses one fresh session per task** — no context rot, no compact issues, every task gets Claude at full quality.

---

## Lesson 2: Install the Skill

```bash
mkdir -p ~/.claude/skills/24x7/scripts

curl -L https://github.com/GodModeAI2025/NightShift/raw/main/24x7/SKILL.md -o ~/.claude/skills/24x7/SKILL.md
curl -L https://github.com/GodModeAI2025/NightShift/raw/main/24x7/scripts/build_zip.py -o ~/.claude/skills/24x7/scripts/build_zip.py
```

**Verify:** Tell Claude: "Set up a 24x7 runner at /tmp/test-workspace". If Claude responds with workspace setup and idle behavior selection, the skill is installed.

---

## Lesson 3: Generate the Workspace

Tell Claude:

```
Set up a 24x7 runner at /Users/me/claude-workspace with idle behavior cleanup
```

Claude asks for:
1. **Workspace path** — where the runner lives
2. **Idle behavior** — what Claude does when the inbox is empty

### Idle Behavior Options

| Option | What Happens | API Cost |
|--------|-------------|----------|
| cleanup | Tidy workspace, collect TODOs from completed tasks | Low |
| docs | Update workspace README with task summaries | Low |
| tests | Suggest tests for code in completed tasks | Medium |
| sleep | Do nothing, just wait | Zero |

Choose `sleep` if API costs are a concern. The runner will simply poll the inbox every 30 seconds without calling Claude.

---

## Lesson 4: Understand the Folder Structure

```
workspace/
├── inbox/           ← YOU put task folders here
│   └── my-task/
│       ├── task.md      ← The assignment (required)
│       └── materials/   ← Input files (optional)
│           ├── code.ts
│           └── spec.md
│
├── working/         ← RUNNER moves tasks here during processing
│
├── outbox/          ← RUNNER puts completed tasks here
│   └── my-task/
│       ├── task.md      ← Original assignment
│       ├── materials/   ← Original input
│       ├── output/      ← RESULTS — this is what you want
│       └── log.md       ← What Claude did
│
├── failed/          ← RUNNER puts failed/timed-out tasks here
│
└── idle/            ← What Claude does when queue is empty
    └── idle-tasks.md
```

**The flow:**
1. You create a folder in `inbox/` with a `task.md`
2. Runner detects it, moves it to `working/`
3. Claude processes it in a fresh session
4. On success → `outbox/`. On failure → `failed/`
5. Runner checks inbox again

---

## Lesson 5: Write a task.md

Every task needs a `task.md` file. The format:

```markdown
## Task: [Title]
Priority: [high/medium/low]

### Assignment
[What exactly to do — be specific]

### Input
[Which files in materials/ are relevant and what they contain]

### Expected Output
[What should appear in output/ — file names, formats]
```

### Example: Code Generation

```markdown
## Task: Create a REST API client
Priority: high

### Assignment
Create a TypeScript REST API client for the JSONPlaceholder API.
Include methods for GET, POST, PUT, DELETE on /posts and /users.
Add proper error handling and TypeScript interfaces for all response types.

### Input
- materials/api-spec.md — API endpoint documentation

### Expected Output
- output/api-client.ts — The client class
- output/types.ts — TypeScript interfaces
- output/api-client.test.ts — Unit tests
```

### Example: Research Task

```markdown
## Task: Compare edge computing frameworks
Priority: low

### Assignment
Research current edge computing frameworks for IoT sensor data.
Compare at least 4 frameworks on: cost, latency, offline capability, language support.

### Input
- materials/requirements.md — Our technical requirements

### Expected Output
- output/comparison.md — Table comparing frameworks
- output/recommendation.md — Reasoned recommendation with pros/cons
```

### Example: File Transformation

```markdown
## Task: Convert CSV to typed JSON
Priority: medium

### Assignment
Read the customer CSV, validate all fields, convert to typed JSON.
Flag rows with missing email or invalid phone numbers.

### Input
- materials/customers.csv — Raw customer data (5000 rows)

### Expected Output
- output/customers.json — Clean, typed JSON array
- output/invalid-rows.json — Rows that failed validation with reasons
- output/report.md — Summary: total, valid, invalid, by error type
```

### Quality Rules for task.md

Good tasks are **specific, bounded, and verifiable**:

- Specify file names for expected output
- Include concrete acceptance criteria
- Provide all necessary input in `materials/`
- Keep scope to what Claude can finish in under 60 minutes

Bad tasks are vague: "improve the codebase" or "fix everything". Claude will guess, and nobody is there to correct.

---

## Lesson 6: Start and Monitor

### Copy the Files Into the Workspace

```bash
cd /your/workspace

# The * glob does not match dotfiles, so .claude needs its own step
cp -r /path/to/24x7-setup/* .

# Hook configuration. An existing settings.json is never overwritten.
if [ -e .claude/settings.json ]; then
  echo "STOP: .claude/settings.json exists, merge it instead of copying (see below)"
else
  mkdir -p .claude
  cp -R /path/to/24x7-setup/.claude/. .claude/
fi

# Without this file the runner has no hooks at all
test -f .claude/settings.json && echo "hooks in place" || echo "WARNING: no hooks"
```

**If `.claude/settings.json` already exists**, merge instead of copying. The
command keeps your own entries and appends the 24x7 hooks per event type:

```bash
jq -s '(.[0].hooks // {}) as $mine | (.[1].hooks // {}) as $new
       | (.[0] * .[1])
       | .hooks = (reduce (($mine | to_entries[]), ($new | to_entries[])) as $e
                   ({}; .[$e.key] = ((.[$e.key] // []) + $e.value)))' \
  .claude/settings.json /path/to/24x7-setup/.claude/settings.json \
  > .claude/settings.merged.json

# read it, then take it over
mv .claude/settings.merged.json .claude/settings.json
```

### Start the Runner

```bash
cd /your/workspace
chmod +x *.sh
./runner-bg.sh          # Starts in background
```

Output:
```
Running as PID 12345
Log:      /tmp/24x7-20260412.log
Watchdog: ./watchdog.sh
Stop:     kill 12345
```

### Monitor with Watchdog

```bash
./watchdog.sh
```

Shows live status every 60 seconds:
```
✅ 14:32:01: OK (12s) | inbox: 3 | working: 1 | done: 8 | failed: 0
✅ 14:33:01: OK (5s)  | inbox: 2 | working: 1 | done: 8 | failed: 0
✅ 14:34:01: OK (3s)  | inbox: 2 | working: 0 | done: 9 | failed: 0
```

### Drop a Task While Running

```bash
mkdir -p inbox/my-new-task/materials
cp my-files.* inbox/my-new-task/materials/
nano inbox/my-new-task/task.md
# Done — runner picks it up within 30 seconds
```

### Collect Results

```bash
ls outbox/my-new-task/output/       # Your deliverables
cat outbox/my-new-task/log.md       # What Claude did
```

### Stop the Runner

```bash
kill $(cat /tmp/24x7.pid)
# Or
pkill -f "runner.sh"
```

The runner handles SIGTERM gracefully: the current task moves to `failed/` with a note, the PID file is cleaned up.

---

## Lesson 7: Handle Failures

Tasks in `failed/` have a `log.md` explaining what went wrong:

```bash
cat failed/my-task/log.md
```

Common failures:

| Failure | log.md says | Fix |
|---------|------------|-----|
| Timeout (default 60 min) | `TIMEOUT` | Simplify the task or increase MAX_SECONDS in runner.sh |
| Claude error | `EXIT CODE: 1` | Check if the task.md is clear and materials are complete |
| Runner stopped | `ABBRUCH: Runner wurde beendet` | Task was in progress when you killed the runner. Move back to inbox to retry: `mv failed/my-task inbox/` |

### Retry a Failed Task

```bash
mv failed/my-task inbox/my-task
# Runner picks it up again
```

---

## Lesson 8: What to Watch Out For

### API Costs — The Biggest Risk
24x7 generates **continuous** API calls. Even idle tasks (cleanup, docs, tests) cost money. A runner processing 10 tasks per day might cost $20–100/day. Set idle to `sleep` to stop costs when the inbox is empty. Monitor at console.anthropic.com.

### Sandbox Is Not Default
Activate explicitly: `sandbox-exec -f sandbox.sb ./runner.sh`. Without it, Claude has full access to your user account. On Linux, use Docker.

### Tasks Are Sequential
The runner processes one task at a time. If you need parallel processing, start multiple runners in separate workspaces.

### No Shared State Between Tasks
Each task gets a fresh Claude session. Claude does not remember the previous task. If tasks depend on each other, include the context in `materials/`.

### Task Timeout
Default: 60 minutes. Tasks taking longer are killed and moved to `failed/`. Adjust `MAX_SECONDS` in `runner.sh` if needed.

### Workspace Isolation
Claude can only work within the workspace. The CLAUDE.md rules and the sandbox enforce this. Claude cannot access your home directory, other projects, or the internet (except the Anthropic API).

---

## Lesson 9: Configuration

Edit these values in `runner.sh`:

| Variable | Default | What It Does |
|----------|---------|-------------|
| `POLL` | 30 | Seconds between inbox checks |
| `MAX_SECONDS` | 3600 | Timeout per task (60 min) |
| `IDLE_SECONDS` | 900 | Timeout for idle tasks (15 min) |

Edit `idle/idle-tasks.md` to change what Claude does when the inbox is empty.

---

## Practice Exercise

1. Create a workspace: `mkdir -p /tmp/24x7-test && cd /tmp/24x7-test`
2. Install the 24x7 skill
3. Tell Claude: "Set up a 24x7 runner at /tmp/24x7-test with idle behavior sleep"
4. Copy the generated files and start the runner
5. Drop three tasks:
   - `inbox/task-1/task.md` — "Create a haiku about programming. Output: output/haiku.md"
   - `inbox/task-2/task.md` — "List the first 20 prime numbers. Output: output/primes.md"
   - `inbox/task-3/task.md` — "Write a bash one-liner that counts files in the current directory. Output: output/oneliner.md"
6. Watch the watchdog as tasks are processed
7. Collect results from `outbox/`

---

**Source code:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Impressum:** [godmodeai2025.github.io/MarkZimmermann](https://godmodeai2025.github.io/MarkZimmermann/)
