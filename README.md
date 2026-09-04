# Nightshift & 24x7 — Autonomous Claude Code Skills

[![CI](https://github.com/GodModeAI2025/NightShift/actions/workflows/ci.yml/badge.svg)](https://github.com/GodModeAI2025/NightShift/actions/workflows/ci.yml)

Two skills that turn Claude Code from an interactive tool into an autonomous worker. Nightshift runs planned project work overnight. 24x7 runs an endless task queue.

**Landing page:** [godmodeai2025.github.io/NightShift](https://godmodeai2025.github.io/NightShift/)

---

## What This Is

Claude Code is powerful but requires constant babysitting. Every file edit, every shell command needs your approval. On longer tasks, context gets compressed and Claude forgets the plan. And if you walk away, Claude stops.

These two skills solve that. They generate a complete setup — runbook, hooks, watchdog, sandbox — that lets Claude Code work autonomously while you sleep, work on something else, or just aren't at the terminal.

**Nightshift** is for planned project work: you describe a task, choose a genre template, get a validated runbook, and Claude executes it overnight. One task, one project, one clean git commit in the morning.

**24x7** is for continuous work: you drop task folders into an inbox, Claude processes them one by one, and results appear in an outbox. An endless loop that runs until you stop it.

Both skills are Claude Code skills — they run inside Claude (either Claude.ai or Claude Code CLI) and generate all files as a setup package. You don't install the skills on your machine directly; you install them into Claude's skill directory, then ask Claude to generate the setup for your specific project.

---

## How It Works (The Architecture)

### The Core Problem

Running Claude Code with `--dangerously-skip-permissions` alone fails after ~20 minutes on longer tasks:

1. **Context compression** — Claude's context window fills up, `/compact` runs automatically, and Claude loses the plan, the conventions, and which steps are already done
2. **No guardrails** — Without approval prompts, a hallucinated `rm -rf ~/` has full permission to execute. This has happened in documented incidents.
3. **No monitoring** — You don't know if Claude is still working, stuck in a loop, or has crashed

### The Solution: Four Layers

Both skills build four layers of protection around `--dangerously-skip-permissions`:

**Layer 1: The Runbook (External Memory)**
A markdown file with checkboxes that Claude reads before each step. After context compression, a hook tells Claude to re-read the runbook and continue at the next unchecked item. The runbook is Claude's external memory — it survives any number of compressions.

**Layer 2: Hooks (Guardrails)**
Claude Code hooks are scripts that fire on specific events:
- `PreToolUse` — Carries `"matcher": "Bash"`, so it runs before every Bash call and never sees `Write` or `Edit`. Blocks command patterns like `rm -rf /`, `sudo`, `chmod 777`, `curl | bash`, `eval`.
- `PostToolUse` — Runs after every tool call. Writes a heartbeat timestamp to a log file.
- `SessionStart` (compact matcher) — Fires after every context compression. Injects "re-read the runbook" into Claude's context.
- `Stop` (Nightshift only) — Fires every time Claude finishes a response. Every 5 completed steps, reminds Claude of autonomy zones and error budget.

Hooks fire even with `--dangerously-skip-permissions`. A `PreToolUse` hook returning exit code 2 blocks the tool call unconditionally.

**Layer 3: macOS Sandbox (Kernel-Level Isolation)**
A `sandbox-exec` profile that restricts Claude's filesystem access at the kernel level. Claude can only write to the project directory and `/tmp`. Even if Claude tries `rm -rf ~/`, the kernel blocks it, without the hook having to catch it. This is the only layer a kernel enforces, and it enforces writes: reads outside the project and outbound network traffic stay open. See [What the Sandbox Does Not Cover](#what-the-sandbox-does-not-cover) and [SECURITY.md](SECURITY.md).

Note: `sandbox-exec` is deprecated by Apple but still functional on current macOS versions. It uses Seatbelt, a kernel-level sandbox framework.

**Layer 4: Watchdog (Liveness Monitoring)**
A separate script that checks the heartbeat file. If Claude hasn't written a heartbeat in N minutes (default: 10), it raises an alarm — either a macOS notification or a message you can hook into your own alerting system.

### Why Fresh Sessions Matter (24x7 Design)

The 24x7 skill does NOT run Claude as one long session. Long sessions degrade — a phenomenon called "context rot" where Claude becomes increasingly unreliable after hours of accumulated context. Instead:

1. The bash loop (`runner.sh`) is the daemon — it runs forever
2. For each task, it spawns a fresh `claude -p` call
3. Claude processes the task, writes results, exits cleanly
4. The loop checks for the next task

This means every task gets Claude at full quality. No accumulated errors, no context rot, no compact-related amnesia.

---

## Nightshift: Genre Templates and Validation

### What Are Genre Templates?

When you tell Nightshift "migrate auth to JWT", it doesn't just write "migrate auth to JWT" into the runbook. It detects the task type (migration) and applies a genre template with predefined phases:

| Genre | Phases | Use When |
|-------|--------|----------|
| refactoring | Analysis → Test coverage → Restructure → Verify → Cleanup | Changing code structure without changing behavior |
| feature | Prep → Structure → Core logic → Integration → Tests → Cleanup | Adding new functionality |
| migration | Compat check → Parallel run → Stepwise migration → Verify → Remove old | Switching frameworks, versions, schemas |
| bugfix | Reproduce → Root cause → Fix → Regression test → Cleanup | Systematic debugging |
| testing | Coverage analysis → Prioritize → Write tests → Verify | Improving test coverage |
| cleanup | Inventory → Prioritize → Clean → Verify | Tech debt, formatting, dependencies |
| devops | Current state → Configure → Test → Deploy check | CI/CD, infrastructure |
| documentation | Inventory → Structure → Content → Review | Docs, README, API docs |

Each genre also includes risk checks specific to the task type. A migration genre asks "Is there a rollback strategy? Could data be lost?" A refactoring genre asks "Are existing tests green before starting?"

### Autonomy Zones

Every runbook includes three autonomy zones (inspired by [AlpiType's Approval Loop article](https://alpitype.de/insights/ki-agenten-approval-loop/)):

- **Green (free):** Read files, create/edit in src/tests/docs, install dependencies, run tests, git add + commit
- **Yellow (log required):** Delete files, modify config files, change more than 3 files at once — Claude must document the reason in log.md
- **Red (forbidden):** Access files outside the project, touch secrets/credentials, force-push

This gives Claude a decision framework. Without it, Claude either hesitates on trivial operations or overreaches on critical ones.

### Error Budget

The runbook defines how many test failures are acceptable:

- 1 failing test: Try to fix, max 2 attempts, then continue
- 2-3 failing tests: Warning in log.md, finish the phase
- Over 3 failing tests: STOP, `git stash`, write log.md

Without an error budget, Claude either stops at the first flaky test (wasting the entire overnight run) or ignores real regressions.

### 15-Point Validation

Before generating the setup, the skill validates the runbook against 15 checks:

**Structure:** Has preconditions? Has verification phase? Has git commit in conclusion? Has rollback instructions? Between 5-20 steps?

**Quality:** Every step contains a file path, command, or concrete action? No vague steps like "implement auth"? Test command is concrete?

**Safety:** No `rm -rf` in steps? No hardcoded secrets? No actions outside the project directory?

**Autonomy:** Has all three zones (green/yellow/red)? Has error budget? Error budget has a stop condition?

Validation is not a gate. The generator prints the score and writes the ZIP even when checks fail, so a failed check is a prompt to fix the runbook, not a stop.

### Checkpoint Repetition

Every 5 completed steps (checked boxes in the runbook), a `Stop` hook fires and reminds Claude of the autonomy zones and error budget. This prevents drift during long runs — Claude re-reads its constraints regularly, not just after context compression.

### Stall Detection (Loop Prevention)

The Stop hook doesn't just check for checkpoints — it tracks progress. If the number of completed runbook steps hasn't increased after 3 consecutive checks, a STALL WARNING is injected into Claude's context. This catches the most common failure mode in autonomous runs: Claude gets stuck on a failing test and retries it endlessly, burning API credits without making progress.

The warning tells Claude to check its error budget and skip the step if the budget allows it. If the budget doesn't allow skipping, Claude stops the run and writes a log — which is the correct behavior for a real regression.

The watchdog sees heartbeats during a stall (Claude is alive and working), so without stall detection, you'd only discover the loop in the morning when you check the runbook and see step 7 still unchecked after 6 hours.

### Run Memory (decisions.md)

Nightshift runs are ephemeral — Claude starts fresh each time. But architecture decisions made in one run should inform the next. If Tuesday's run chose PostgreSQL over SQLite, Wednesday's run should know that.

The solution: a `decisions.md` file in the project root that persists across runs.

- The runbook's conclusion phase includes a step: "Document decisions in decisions.md"
- The CLAUDE-nightshift.md instructs Claude to read `decisions.md` at the start of every run
- Format: date, decision, reasoning. Append-only, never overwrite.

This gives cross-run persistence without requiring a long-lived session or external memory system. It's not learning — it's structured remembering.

The 24x7 skill uses the same pattern at workspace level: each task reads `decisions.md` from the workspace root and appends relevant decisions after completing work.

---

## Installation

### Prerequisites

- **Claude Code CLI** installed and authenticated (`claude` command available)
- **bash**, **python3 3.9 or newer**, **jq** in your PATH (the build scripts are tested against the macOS system Python 3.9)
- **timeout** or **gtimeout** for 24x7 only. macOS does not ship `timeout`; `brew install coreutils` provides `gtimeout`. The runner uses whichever it finds and refuses to start without one.
- **macOS** recommended (for `sandbox-exec`). Works on Linux without the sandbox layer.
- A **git repository** for your project (Nightshift) or any directory (24x7)

### Install the Skills

Download both skills from the latest release and unpack them into Claude's skill directory:

```bash
mkdir -p ~/.claude/skills
curl -LO https://github.com/GodModeAI2025/NightShift/releases/latest/download/nightshift.skill
curl -LO https://github.com/GodModeAI2025/NightShift/releases/latest/download/24x7.skill
unzip nightshift.skill -d ~/.claude/skills/
unzip 24x7.skill -d ~/.claude/skills/
```

Both files are ZIP archives, `.skill` is only the extension. Each one unpacks into a single directory, `~/.claude/skills/nightshift/` and `~/.claude/skills/24x7/`, containing `SKILL.md`, `scripts/build_zip.py`, the license, and a `VERSION` file naming the release it came from.

The links resolve to the newest tag. As long as no tag exists they return 404. In that case, and whenever you want the current state of `main` rather than a release, clone and copy:

```bash
git clone https://github.com/GodModeAI2025/NightShift.git
mkdir -p ~/.claude/skills
cp -r NightShift/nightshift NightShift/24x7 ~/.claude/skills/
```

The version of a release is in [VERSION](VERSION), what changed is in [CHANGELOG.md](CHANGELOG.md).

### Verify Installation

Open Claude Code and ask:

```
Set up a nightshift run for /my/project — migrate auth to JWT
```

If the skill triggers, you'll see it generate a runbook, validate it, and produce the setup files. If Claude doesn't recognize the skill, check that `~/.claude/skills/nightshift/SKILL.md` exists.

---

## Usage: Nightshift

### Step 1: Ask Claude to Generate the Setup

In Claude (claude.ai or Claude Code), say something like:

```
Set up a nightshift run for /Users/me/projects/my-api — refactor the auth module to use JWT tokens
```

Claude will:
1. Detect the genre (refactoring)
2. Ask you to confirm
3. Generate a runbook with concrete steps
4. Validate it (15 checks)
5. Produce the setup files

### Step 2: Copy Files Into Your Project

```bash
cd /your/project
cp nightshift-setup/runbook.md .
cp nightshift-setup/nightshift-*.sh .
cp nightshift-setup/nightshift-sandbox.sb .
cat nightshift-setup/CLAUDE-nightshift.md >> CLAUDE.md
chmod +x nightshift-*.sh

# Hook configuration. An existing settings.json is never overwritten.
if [ -e .claude/settings.json ]; then
  echo "STOP: .claude/settings.json exists, merge it instead of copying (see below)"
else
  mkdir -p .claude
  cp -R nightshift-setup/.claude/. .claude/
fi

# Without this file the run has no hooks and no protection layer
test -f .claude/settings.json && echo "hooks in place" || echo "WARNING: no hooks"
```

**If `.claude/settings.json` already exists**, merging keeps your own hooks,
permissions, and MCP settings and appends the Nightshift hooks per event type:

```bash
jq -s '(.[0].hooks // {}) as $mine | (.[1].hooks // {}) as $new
       | (.[0] * .[1])
       | .hooks = (reduce (($mine | to_entries[]), ($new | to_entries[])) as $e
                   ({}; .[$e.key] = ((.[$e.key] // []) + $e.value)))' \
  .claude/settings.json nightshift-setup/.claude/settings.json \
  > .claude/settings.merged.json

# read it, then take it over
mv .claude/settings.merged.json .claude/settings.json
```

### Step 3: Commit Your Current State

This is your safety net. If anything goes wrong, `git checkout .` brings you back here.

```bash
git add -A && git commit -m "Checkpoint before Nightshift"
```

### Step 4: Start

**Foreground** (you see the output):
```bash
./nightshift-run.sh
```

**Background** (terminal can be closed):
```bash
./nightshift-run-bg.sh
```

**With macOS sandbox** (recommended):
```bash
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh
```

### Step 5: Monitor (Optional)

In a second terminal:

```bash
./nightshift-watchdog.sh        # Alerts after 10 min without heartbeat
./nightshift-watchdog.sh 300    # Alerts after 5 min
```

### Step 6: Check Results in the Morning

```bash
git log --oneline -5            # See the commit
git diff HEAD~1                 # See what changed
cat runbook.md                  # See which steps were completed [x]
```

### Emergency: Undo Everything

```bash
git checkout .                  # Revert all changes
# or
git stash                       # Save changes for review
```

---

## Usage: 24x7

### Step 1: Ask Claude to Generate the Setup

```
Set up a 24x7 runner at /Users/me/claude-workspace with idle behavior cleanup
```

Claude will generate the workspace structure with runner, watchdog, hooks, and sandbox profile.

### Step 2: Install and Start

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

# Without this file the daemon runs with no hooks at all
test -f .claude/settings.json && echo "hooks in place" || echo "WARNING: no hooks"

chmod +x *.sh
./runner-bg.sh
```

**If `.claude/settings.json` already exists**, merging keeps your own entries
and appends the 24x7 hooks per event type:

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

### Step 3: Drop Tasks

Create a folder in `inbox/` with a `task.md` and optionally a `materials/` directory:

```bash
mkdir -p inbox/my-task/materials
```

Write the assignment:

```bash
cat > inbox/my-task/task.md << 'EOF'
## Task: Create a REST API client
Priority: high

### Assignment
Create a TypeScript REST API client for the JSONPlaceholder API.
Include methods for all CRUD operations on /posts and /users.
Add error handling and TypeScript types.

### Input
- materials/api-spec.md — API specification

### Expected Output
- output/api-client.ts — The client
- output/types.ts — TypeScript interfaces
- output/api-client.test.ts — Unit tests
EOF
```

Copy input files:

```bash
cp my-api-spec.md inbox/my-task/materials/api-spec.md
```

The runner picks it up automatically. Results appear in `outbox/my-task/output/`.

### Step 4: Monitor

```bash
./watchdog.sh
```

Shows live status: `✅ 14:32:01: OK (12s) | 📥3 🔄1 ✅12 ❌0`

### Step 5: Collect Results

```bash
ls outbox/my-task/output/       # Your files
cat outbox/my-task/log.md       # What Claude did
```

### Idle Behavior

When the inbox is empty, Claude can:

- **cleanup** — Tidy the workspace, collect TODOs from outbox files
- **docs** — Update a workspace README with completed task summaries
- **tests** — Suggest tests for code in completed tasks
- **sleep** — Do nothing, save API costs

Configure by editing `idle/idle-tasks.md` or setting the idle behavior when generating the setup.

---

## Important: What to Watch Out For

### API Costs

Both skills run Claude Code in headless mode. Every tool call, every file read, every response consumes API credits. An overnight Nightshift run might cost $5-50 depending on task complexity. A 24x7 runner generates continuous costs.

- Monitor your usage at [console.anthropic.com](https://console.anthropic.com)
- For 24x7: set idle to `sleep` if cost is a concern — this prevents Claude from burning credits when no tasks are waiting
- Both runners show a cost warning at startup

### The Sandbox Is Not Installed by Default

The generated `sandbox.sb` / `nightshift-sandbox.sb` file is just a profile. You must explicitly use it:

```bash
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh
```

Without `sandbox-exec`, Claude has full access to everything your user account can reach. The `PreToolUse` hook greps the command text, so it catches typos and obvious mistakes. It carries `"matcher": "Bash"`, which means `Write` and `Edit` never reach it.

### What the Sandbox Does Not Cover

The sandbox is the only layer that a kernel enforces, and what it enforces is writes. It restricts neither reads nor network traffic. The generated profile grants `file-read*` on `$HOME/.claude` and `$HOME/.config`, and it allows `(allow network-outbound (remote tcp "*:443"))` without a destination. `~/.claude` holds the transcripts of your other projects, `~/.config` commonly holds CLI tokens. Anything the run can read, it can also send.

Calling the sandbox a security boundary is only accurate for writes to the filesystem. [SECURITY.md](SECURITY.md) has the threat model, the trust boundaries, and the list of known gaps.

### Linux Has No sandbox-exec

Docker with the project mounted is the route that gives you an enforced boundary. A dedicated user account scopes file access with Unix permissions, which is weaker and takes more than three lines:

```bash
sudo useradd -m clauderunner
sudo cp -r /your/project /home/clauderunner/project
sudo chown -R clauderunner: /home/clauderunner/project
sudo -u clauderunner /home/clauderunner/project/nightshift-run.sh
```

Three things about that recipe:

- The copy that `sudo cp -r` creates belongs to root. Without the `chown`, the runner account cannot write in its own working copy.
- `nightshift-run.sh` starts with a `cd` to the path that was set when the setup was generated. Regenerate the setup with `NIGHTSHIFT_PROJECT=/home/clauderunner/project`, otherwise the run leaves the new account and works in the original directory.
- The new account has no Claude Code credentials. Authenticate as that user once before the first run.

Even then the account reaches the network and can read every world-readable file on the machine. This is permission scoping, not isolation.

### Git Is Your Undo Button (Nightshift)

Always commit before starting a Nightshift run. Without a clean git state, you have no rollback. The runner checks for uncommitted changes and warns you (non-blocking).

### PID Lock Prevents Double Starts

Both runners write a PID file. If you try to start a second instance, it refuses with a clear error. To force a restart after a crash:

```bash
rm /tmp/nightshift.pid          # or /tmp/24x7.pid
```

### The Runbook Quality Matters

Vague runbook steps produce vague results. "Implement auth" can mean anything — Claude will guess, and in headless mode, nobody corrects the guess. Good steps look like:

```
- [ ] Create src/services/token-service.ts with functions: generateAccessToken(userId), verifyToken(token)
```

The 15-point validation catches the worst offenders, but you should review the runbook before starting.

### Long Runs and Context Compression

Nightshift handles context compression with two mechanisms:
1. `SessionStart` hook re-injects "read the runbook" after every `/compact`
2. `Stop` hook repeats autonomy zones and error budget every 5 steps

This works well for 10-20 step runbooks. For very long tasks (30+ steps), split into multiple Nightshift runs — the quality degrades even with these mechanisms.

24x7 avoids the problem entirely by using fresh sessions per task.

### Graceful Shutdown

Both runners handle SIGTERM and SIGINT (Ctrl+C) gracefully. On 24x7, an in-progress task is moved to `failed/` with a note. The PID file is cleaned up.

```bash
# Graceful stop
kill $(cat /tmp/nightshift.pid)

# Or for 24x7
kill $(cat /tmp/24x7.pid)
```

---

## File Reference

### Nightshift Setup Files

| File | Purpose |
|------|---------|
| `runbook.md` | Task plan with checkboxes, autonomy zones, error budget |
| `.claude/settings.json` | All hooks: PreToolUse, PostToolUse, SessionStart, Stop |
| `nightshift-run.sh` | Main script: `claude -p` + `--dangerously-skip-permissions` + PID lock + graceful shutdown |
| `nightshift-run-bg.sh` | Background wrapper using `nohup` |
| `nightshift-watchdog.sh` | Heartbeat monitor with configurable timeout |
| `nightshift-sandbox.sb` | macOS sandbox profile (Seatbelt) |
| `CLAUDE-nightshift.md` | Conventions + run memory (decisions.md) to append to CLAUDE.md |
| `README-nightshift.md` | Quick reference for the generated setup |

### 24x7 Setup Files

| File | Purpose |
|------|---------|
| `runner.sh` | Endless loop: poll inbox → spawn Claude → route results |
| `runner-bg.sh` | Background wrapper using `nohup` |
| `watchdog.sh` | Heartbeat monitor with live inbox/outbox counters |
| `sandbox.sb` | macOS sandbox profile |
| `.claude/settings.json` | PreToolUse + PostToolUse hooks |
| `CLAUDE.md` | Workspace rules: autonomy zones, error tolerance, workspace memory (decisions.md) |
| `idle/idle-tasks.md` | Configurable idle behavior |
| `inbox/beispiel-task/` | Example task with task.md template |

---

## Roadmap

Ordered by what blocks users today. No dates attached, this is a private project.

**Next**

- **A hook that sees more than Bash.** The `PreToolUse` hook carries `"matcher": "Bash"`. `Write` and `Edit` bypass it entirely, and a variable assignment gets past the pattern. A second matcher plus a path check instead of a string match.
- **Egress control.** The seatbelt profile allows outbound 443 to any host. Restricting it to the Anthropic API is what turns a write boundary into something closer to a real one.

**After that**

- **Linux isolation that holds.** A Docker Compose setup with the project mounted, so the Linux route stops being a user-account workaround.
- **A cost ceiling that stops a run.** Both runners print a warning at startup and that is the entire mechanism. Nightshift has no timeout at all.
- **A morning receipt.** One JSON file per run: steps done against steps open, `git diff --stat`, the decisions log, the exit code.

**Test coverage**

CI compiles both generators under Python 3.9, runs them, checks the generated ZIP, drives the block list of the `PreToolUse` hook against a table of dangerous and harmless commands, and builds the release artifacts on every push to check what they do and do not contain. The generated shell scripts are only checked for syntax; nothing executes a runner, a watchdog, or the sandbox profile. See [.github/workflows/ci.yml](.github/workflows/ci.yml) and [tests/](tests).

## Acknowledgments

Autonomy zones and error budget inspired by [AlpiType — Solving the AI Agent Approval Loop](https://alpitype.de/insights/ki-agenten-approval-loop/)

## Disclaimer

This project was created privately, to the best of the author's knowledge. Use at your own risk. No warranty of completeness, correctness, or fitness for any particular purpose.

## License

Apache-2.0 — see [LICENSE](LICENSE)
