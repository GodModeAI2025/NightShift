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
- `PreToolUse` — Two entries, because one question is not the other. `"matcher": "Bash"` examines the command text and blocks patterns like `rm -rf /`, `sudo`, `chmod 777`, `curl | bash`, `eval`. `"matcher": "Write|Edit|MultiEdit|NotebookEdit"` examines the target path and blocks every write outside the project directory. See [The Path Guard](#the-path-guard).
- `PostToolUse` — Runs after every tool call. Writes a heartbeat timestamp to a log file.
- `SessionStart` (compact matcher) — Fires after every context compression. Injects "re-read the runbook" into Claude's context.
- `Stop` (Nightshift only) — Fires every time Claude finishes a response. Every 5 completed steps, reminds Claude of autonomy zones and error budget.

Hooks fire even with `--dangerously-skip-permissions`. A `PreToolUse` hook returning exit code 2 blocks the tool call unconditionally.

**Layer 3: Isolation (Container by Default)**
Nightshift generates a `Dockerfile` and a `docker-compose.yml`. The container mounts the project as `/project` and nothing else from the host — no home directory, no `~/.claude`, no neighbouring projects. Outbound traffic runs through a proxy that only lets `api.anthropic.com` through and answers everything else with 403. `nightshift-run.sh` refuses to start when it finds neither a container nor a sandbox profile; `NIGHTSHIFT_ALLOW_UNSANDBOXED=1` is the deliberate way out.

The `sandbox-exec` profile stays as the macOS option. It restricts writes at the kernel level: Claude can only write to the project directory and `/tmp`, and `rm -rf ~/` fails without the hook having to catch it. What it does not restrict is reads outside the project and outbound traffic. Apple has deprecated `sandbox-exec`; it still works on current macOS versions. See [What the Sandbox Does Not Cover](#what-the-sandbox-does-not-cover) and [SECURITY.md](SECURITY.md).

24x7 gets the same two. `runner.sh` measures the same way, refuses to start unfenced with exit code 3, and `CLAUDE_24X7_ALLOW_UNSANDBOXED=1` is the way past it. Its container mounts the workspace as `/workspace` and starts the daemon in it; `./24x7-docker.sh` builds and runs it, tasks keep arriving in `inbox/` on the host. Dockerfile, Compose file, docker script, seatbelt profile and the isolation check are one implementation in `gemeinsam.py`, filled with different names.

**Layer 3b: Cost Governor (Nightshift)**
`nightshift-cost.sh` reads Claude's `stream-json` output, adds up the `usage` fields per model and estimates the dollar figure from a dated price table. When the estimate passes the budget, it terminates Claude's whole process group — a grandchild that outlived the parent used to keep the pipe open and the run hanging — and the run ends with exit code 9. Without `jq`, and equally when the stream carries no `usage` events at all, it measures nothing, says `unbekannt` and lets the run continue — a broken counter must not kill a working night, and it must not report a zero it never measured.

**Layer 4: Watchdog (Liveness Monitoring and Restart)**
A separate script that checks the heartbeat file. If Claude hasn't written a heartbeat in N minutes (default: 10), it acts. Which action is `NIGHTSHIFT_WATCHDOG_AKTION` (`CLAUDE_24X7_WATCHDOG_AKTION` for 24x7): `melden` reports and is the default, `beenden` terminates the run, `neustart` terminates it and starts it again. A run that ended on its own is never restarted, because the watchdog only restarts what it just terminated itself. See [The Restart Policy](#the-restart-policy).

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
- **Docker** with **Docker Compose v2** for the Nightshift default path. Same on Linux and macOS. Without Docker the run needs `NIGHTSHIFT_ALLOW_UNSANDBOXED=1` or the macOS `sandbox-exec` option.
- An **ANTHROPIC_API_KEY** for the container path. The container has its own home and does not see an OAuth login on the host.
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

**In the container** (the default):
```bash
export ANTHROPIC_API_KEY=sk-ant-...
./nightshift-docker.sh
```

Builds both images, mounts the project as `/project`, runs the night, tears the containers down again. The budget defaults to 25 USD; `NIGHTSHIFT_BUDGET_USD=5 ./nightshift-docker.sh` changes it for one run.

**With the macOS sandbox** (option):
```bash
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh
```

No environment variable is involved. The runner probes whether it is fenced: under the profile it can list the project but not `/Users`, and that is what earns the `seatbelt` state.

**Without isolation** (aborts unless you say so):
```bash
./nightshift-run.sh                                 # exit code 3
NIGHTSHIFT_ALLOW_UNSANDBOXED=1 ./nightshift-run.sh  # runs, on your head
```

**Background** (host, terminal can be closed):
```bash
./nightshift-run-bg.sh
```

### Step 5: Monitor (Optional)

In a second terminal:

```bash
./nightshift-watchdog.sh        # Alerts after 10 min without heartbeat
./nightshift-watchdog.sh 300    # Alerts after 5 min
```

### Step 6: Check Results in the Morning

Every run writes a receipt, including a run that crashed:

```bash
cat nightshift-receipts/*/receipt.md     # Steps, diff, cost, isolation, exit code
cat nightshift-receipts/*/receipt.json   # Same thing, machine readable
```

Fields the run could not determine read `"unbekannt"`, never `0` or `null`. Cost stays unknown when `jq` is missing or the output format changed; isolation stays unknown when the run had none.

The raw material is still there if you want it:

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

Both skills run Claude Code in headless mode. Every tool call, every file read, every response consumes API credits. A 24x7 runner generates continuous costs.

Nightshift measures and stops. The counter sums the `usage` fields of the `stream-json` stream and estimates the dollars from a price table with a date on it; at the budget it kills Claude's process group. On a real run against the API the estimate came out at 0.25860 USD against the 0.25863 USD Claude reported for the same request. A model the table does not know is billed at twice the most expensive known row, because a newer model can be dearer than anything in the table. The number in `receipt.json` is still an estimate, not an invoice — the invoice is at [console.anthropic.com](https://console.anthropic.com), and prices move.

```bash
NIGHTSHIFT_BUDGET_USD=5 ./nightshift-docker.sh          # dollar ceiling, default 25
NIGHTSHIFT_BUDGET_TOKENS=2000000 ./nightshift-run.sh    # additional token ceiling
```

24x7 has none of this. It prints a warning at startup and that is the whole mechanism. Set idle to `sleep` there if cost is a concern, so Claude does not burn credits while the inbox is empty.

### Nightshift Refuses to Run Without Isolation

`nightshift-run.sh` measures how it is fenced before it calls Claude. It measures — it does not ask:

| State | How it is reached | How it is verified | Exit |
|---|---|---|---|
| `docker` | `./nightshift-docker.sh`, or any container | `/.dockerenv`, `/run/.containerenv`, `/proc/1/cgroup`, or an overlay root | runs |
| `seatbelt` | `sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh` | the runner can list the project but not `/Users`; the profile denies that read | runs |
| `keine` | plain `./nightshift-run.sh` | neither probe answered | exit code 3 |

`NIGHTSHIFT_SANDBOXED` used to be the whole check, and any word passed it: `NIGHTSHIFT_SANDBOXED=banane` ran on a bare macOS shell with `--dangerously-skip-permissions` and wrote `isolation: banane` into the receipt. It is now a cross-check only. Set it, and if it disagrees with the measurement the run aborts with exit code 3; it grants nothing.

`NIGHTSHIFT_ALLOW_UNSANDBOXED=1` runs anyway, and the receipt then says `keine` — never a word somebody typed. The state ends up in the receipt, so afterwards you can tell how a given night was fenced.

Isolation is not the same as the hook. The `Bash` hook greps command text, so it catches typos and obvious mistakes; the path guard measures a target path and holds against `Write`, `Edit` and `NotebookEdit`. Neither of them stops a read, and neither of them stops a write that a Bash command performs.

24x7 runs the same check, with `CLAUDE_24X7_SANDBOXED` as the cross-check and `CLAUDE_24X7_ALLOW_UNSANDBOXED=1` as the opt-out. What it does not have is a budget and a receipt; those are still Nightshift only.

### The Path Guard

The hook used to carry `"matcher": "Bash"` and nothing else. `Write`, `Edit`
and `NotebookEdit` never reached it, so an unattended run could write any file
on the disk and the protection layer did not even see it. There is a second
`PreToolUse` entry now, and it asks a different question:

| Matcher | Examines | Blocks |
|---|---|---|
| `Bash` | the command text | `rm` against dangerous targets, `sudo`, `mkfs`, `dd` to a device, `chmod 777`, `curl \| bash`, `eval` |
| `Write\|Edit\|MultiEdit\|NotebookEdit` | the target path | every write outside the project directory, plus `.claude/settings.json` inside it |

The path is normalised before the comparison: `~/` becomes the home
directory, `.` and `..` are resolved, a relative path is resolved against the
working directory Claude Code sends with the call. `$PROJECT/../elsewhere/x`
therefore lands outside and gets blocked. `$PROJECT-copy/x` gets blocked too;
the comparison is against the directory, not against a prefix of the string.
Without `jq` neither hook can read its input, and both then block instead of
waving the call through.

The root comes from `NIGHTSHIFT_PROJEKT` (`CLAUDE_24X7_WORKSPACE` for 24x7)
and falls back to the path the setup was generated for. The container sets it
to `/project`, so the same hook fences the run there. That variable belongs to
whoever starts the run: hooks inherit the environment of the Claude process,
and an `export` inside a Bash tool call does not reach it.

Blocking its own configuration is deliberate. A run that may rewrite
`.claude/settings.json` has no barrier, only a suggestion.

**What the path guard does not cover:**

- **Writes through Bash.** `echo > file`, `tee`, `cp`, `mv`, `>>` are Bash
  calls. They go to the first hook, and that one checks no paths. This is the
  largest remaining hole, and it is the reason the container is the default.
- **Reads.** Neither hook looks at `Read`, `Grep` or `cat`. Whatever is
  readable stays readable.
- **Symlinks.** The comparison is textual. A link inside the project that
  points outside is not followed and passes.
- **Two names for one directory.** `/tmp` and `/private/tmp` are two places to
  a text comparison; on macOS they are one directory.
- **Tools from MCP servers.** They carry their own tool names, and no matcher
  here catches them.
- **A settings.json that was never installed.** Both hooks exist only if
  `.claude/settings.json` is in the project. The install step is a separate
  command precisely because `cp -r dir/* .` skips dotfiles.

Measured in CI: 14 write targets that must be blocked and 9 that must pass,
per skill, driven as real tool calls through the hook command taken out of the
generated `settings.json`. Plus `Edit`, `MultiEdit` and `NotebookEdit` on both
sides of the boundary, an input without a path, and a run with `jq` removed
from `PATH`. See [tests/test_pfad_schranke.py](tests/test_pfad_schranke.py).

### What the Sandbox Does Not Cover

The sandbox is the only layer that a kernel enforces, and what it enforces is writes. It restricts neither reads nor network traffic. The generated profile allows `file-read*` broadly, denies `/Users` and `/home` and then re-grants `$HOME/.claude`, `$HOME/.config` and the other tool directories, and it allows `(allow network-outbound (remote tcp "*:443"))` without a destination. `~/.claude` holds the transcripts of your other projects, `~/.config` commonly holds CLI tokens. Anything the run can read, it can also send.

Reads are open on purpose, and it is a concession, not a design goal: a profile that allowed only the handful of paths this one used to list no longer starts any program on current macOS. Measured on Darwin 27, `sandbox-exec -f nightshift-sandbox.sb /bin/echo hi` ended with SIGABRT — the dyld cache sits outside that list. A profile under which nothing runs protects nobody, so the profile now keeps the write fence and the home-directory fence and gives up the read fence it never actually delivered.

Calling the sandbox a security boundary is only accurate for writes to the filesystem. [SECURITY.md](SECURITY.md) has the threat model, the trust boundaries, and the list of known gaps.

### Linux Has No sandbox-exec, and Does Not Need It

The container is the Linux route, and it is the same route on macOS:

```bash
export ANTHROPIC_API_KEY=sk-ant-...
./nightshift-docker.sh
```

What the container gives you that the seatbelt profile does not: reads are fenced too, because nothing but the project is mounted, and outbound traffic is fenced, because the runner hangs in an internal network whose only bridge is a proxy with an allowlist. What it costs: Docker, a build of about a gigabyte, and an API key in the environment rather than an OAuth login on the host.

The dedicated user account remains a weaker fallback for machines without Docker:

```bash
sudo useradd -m clauderunner
sudo cp -r /your/project /home/clauderunner/project
sudo chown -R clauderunner: /home/clauderunner/project
sudo -u clauderunner env NIGHTSHIFT_PROJEKT=/home/clauderunner/project \
    NIGHTSHIFT_ALLOW_UNSANDBOXED=1 \
    bash /home/clauderunner/project/nightshift-run.sh
```

Three things about that recipe:

- The copy that `sudo cp -r` creates belongs to root. Without the `chown`, the runner account cannot write in its own working copy.
- `NIGHTSHIFT_PROJEKT` moves the run into the copy. Without it the script uses the path from generation time and works in the original directory.
- The new account has no Claude Code credentials. Authenticate as that user once before the first run.

Even then the account reaches the network and can read every world-readable file on the machine. That is why the run needs `NIGHTSHIFT_ALLOW_UNSANDBOXED=1`: this is permission scoping, not isolation.

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

### The Restart Policy

The watchdog used to detect a stall and then do nothing about it: one line on
stdout and a macOS notification that nobody sees at three in the morning. It
still detects the same thing, but what it does with it is now a choice.

| `NIGHTSHIFT_WATCHDOG_AKTION` | On a stall |
|---|---|
| `melden` (default) | Report and keep watching. The old behaviour. |
| `beenden` | `TERM` to the PID in `/tmp/nightshift.pid`, `KILL` after `NIGHTSHIFT_WATCHDOG_FRIST` seconds (default 20), then the watchdog exits. |
| `neustart` | The same, then start the run again, at most `NIGHTSHIFT_WATCHDOG_NEUSTARTS` times (default 1). |

24x7 has the same three under `CLAUDE_24X7_WATCHDOG_AKTION`.

`TERM` before `KILL` is not politeness. Both runners trap `TERM` and use it to
shut down: Nightshift ends Claude's process group, 24x7 moves the task it was
working on to `failed/` and writes a note. A watchdog that went straight to
`KILL` would leave a task stuck in `working/` forever.

**A run that ended on its own is never restarted.** That is the whole safety
rule, and it comes from the order of operations rather than from a list of
exceptions: the watchdog restarts only what it just terminated itself, and it
recognises that by a live PID in the PID file. A budget stop terminates the
run, so afterwards there is no live PID, and the watchdog reports instead of
restarting. A crash and a finished run look the same to it. The roadmap asked
for a restart that stays blocked after a budget stop; this is that, without a
second mechanism that could disagree with the first.

**What the watchdog does not cover:**

- **A busy loop.** The heartbeat comes from the `PostToolUse` hook. Claude
  retrying the same failing test forever keeps writing heartbeats, and to the
  watchdog that looks perfectly healthy. The `Stop` hook's stall detector is
  the answer to that case, and it writes text into Claude's context rather
  than stopping anything.
- **A run in the container.** `/tmp` in the container is a tmpfs of its own,
  so the heartbeat never reaches the host and a watchdog started there waits
  forever for a file that will not appear. `docker compose logs -f` is what
  you watch instead. This is the reason a host-side restart policy is not the
  right shape for the default path: `docker compose` restart policies are.
- **The reason for the stall.** It restarts, it does not diagnose. A run that
  hangs on the same step every time burns the restart budget and then stops.
- **Being started at all.** It is a separate script in a second terminal, and
  nothing starts it for you.

Measured in CI against a stand-in run, for both skills: `melden` leaves the
process alive, `beenden` ends it and exits 0, `neustart` ends it and starts the
run script again, a restart budget of 0 ends it without a restart, an already
dead run is reported and not restarted, an unknown action behaves like
`melden`, and the terminated process really receives `TERM` before `KILL`. See
[tests/test_watchdog.py](tests/test_watchdog.py).

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
| `nightshift-run.sh` | Main script: isolation check, `claude -p` + `--dangerously-skip-permissions`, PID lock, graceful shutdown, receipt from the exit trap |
| `nightshift-run-bg.sh` | Background wrapper using `nohup` |
| `nightshift-docker.sh` | Builds the images and runs the night in the container |
| `Dockerfile` | Two targets: `runner` with Claude Code, `egress` with the allowlist proxy |
| `docker-compose.yml` | Project as the only host mount, internal network, read-only root, dropped capabilities |
| `nightshift-cost.sh` | Token counter and budget stop, reads the `stream-json` stream |
| `nightshift-receipt.sh` | Writes `receipt.json` and `receipt.md` per run |
| `nightshift-watchdog.sh` | Heartbeat monitor with configurable timeout |
| `nightshift-sandbox.sb` | macOS sandbox profile (Seatbelt), the option next to the container |
| `CLAUDE-nightshift.md` | Conventions + run memory (decisions.md) to append to CLAUDE.md |
| `README-nightshift.md` | Quick reference for the generated setup |

### 24x7 Setup Files

| File | Purpose |
|------|---------|
| `runner.sh` | Endless loop: poll inbox → spawn Claude → route results |
| `runner-bg.sh` | Background wrapper using `nohup` |
| `24x7-docker.sh` | Builds the container and starts the runner in it |
| `Dockerfile` | Two targets: runner and egress proxy |
| `docker-compose.yml` | Workspace at `/workspace`, internal network, hardening |
| `watchdog.sh` | Heartbeat monitor with live inbox/outbox counters. Host runs only, the container has its own `/tmp` |
| `sandbox.sb` | macOS sandbox profile |
| `.claude/settings.json` | PreToolUse + PostToolUse hooks |
| `CLAUDE.md` | Workspace rules: autonomy zones, error tolerance, workspace memory (decisions.md) |
| `idle/idle-tasks.md` | Configurable idle behavior |
| `inbox/beispiel-task/` | Example task with task.md template |

---

## Roadmap

Ordered by what blocks users today. No dates attached, this is a private project.

**Next**

- **Budget and receipt for 24x7.** The container is there now, the other two are not. The runner measures nothing and leaves a `log.md` per task instead of a report. A budget for a task loop is not the Nightshift counter with a new name: it has to carry a total across tasks, and the counter starts from zero per invocation.
- **Egress control for the seatbelt path.** The container has an allowlist proxy; the seatbelt profile still allows outbound 443 to any host.

**After that**

- **SpecForge tasks.md as a runbook source.** See [Related Projects](#related-projects). The validation checks German section headings and the three zones, so this needs a converter, not a new entry in the genre table.

**Done in the meantime**

- Container isolation as the default for Nightshift, with the run refusing to start unfenced.
- A cost governor that measures first and then stops, with the tokens in the receipt.
- A morning receipt as JSON and Markdown, written from the exit trap so a crashed run has one too.
- A second `PreToolUse` matcher for `Write`, `Edit`, `MultiEdit` and `NotebookEdit` that measures the target path instead of a command string. Both skills, one implementation in `gemeinsam.py`.
- Container isolation for 24x7, from the same templates as Nightshift's, with the runner refusing to start unfenced.
- A restart policy in both watchdogs. A restart after a budget stop stays blocked, because the watchdog only restarts a run it terminated itself.

**Test coverage**

CI compiles both generators under Python 3.9, runs them, checks the generated ZIP, drives the block list of the `PreToolUse` hook against a table of dangerous and harmless commands, drives the path guard against a table of write targets inside and outside the project, unpacks the release artifact and runs the generator from that location, drives the three watchdog actions against a stand-in run, validates the generated `docker-compose.yml` of both skills, runs `nightshift-run.sh` and `runner.sh` against a Claude stub for the isolation check, `nightshift-run.sh` for the budget stop and the receipt, and builds the release artifacts on every push. What CI does not do is start a container: the image build needs a network and minutes, so that proof lives in the pull request rather than in the pipeline. See [.github/workflows/ci.yml](.github/workflows/ci.yml) and [tests/](tests).

## Related Projects

### moinsen-dev/NightShift

[moinsen-dev/NightShift](https://github.com/moinsen-dev/NightShift) is an independent reimplementation of the same idea, not a fork. GitHub reports no fork relationship, and the two repositories share no history. Its `plugins/nightshift/.claude-plugin/plugin.json` names `GodModeAI` as the author and this repository as its home, so the lineage is acknowledged from that side. It ships under the plugin name `nightshift` at version 2.0.0, which is worth knowing before you install both.

No code moved in either direction. Nothing here is derived from that repository, so there is no `NOTICE` file to go with it; if anything is ever taken from there, Apache-2.0 section 4 applies and the attribution comes with it.

Where the two differ, as of 2026-09-04:

- **Both have a shared module now.** The block pattern and both hook bodies live in `gemeinsam.py`, and a test fails if the two generators stop agreeing. The sandbox profile and the watchdog are still there twice; that duplication is real and it is ours.
- **Its blocklist is longer.** Fork bombs, force-push and a strict mode are on it. The hook here has no fork-bomb pattern; `nightshift/SKILL.md` says so in the Security section.
- **Its cost tracker cannot stop a run.** In `plugins/nightshift/scripts/shared/cost_tracker.py`, `CLAUDE_PID` appears exactly once, in the `kill` on line 33, and is never assigned; the budget query uses `grep -oP`, which BSD grep on macOS rejects; and the sums live in the subshell of a pipeline. The counter here writes its state to a file, gets the PID from the runner and kills the process group — `kill -- -PGID` against a group the runner opens with `set -m`, which is what actually reaches a grandchild that outlived its parent — and the budget stop is checked in CI against a stub with exactly such a grandchild. Measuring is the easy half — stopping is the half that has to work.
- **Its zone enforcement still stops at Bash.** `matcher: "Bash"` there, blocked paths matched against command text. Here a second matcher measures the target path of `Write`, `Edit`, `MultiEdit` and `NotebookEdit`, and a table in CI drives real tool calls through the generated hook. What passes in both is a write that a Bash command performs.
- **What is only here:** tests and CI, a tagged release with artifacts, a SECURITY.md, the landing page, and container isolation with an egress allowlist plus a receipt that says what a night cost.

The intended distinguishing feature is executing a `tasks.md` produced by [SpecForge](https://github.com/GodModeAI2025/specforge-ai-skill) as an unattended night. That is not implemented. The 15-point validation expects German section headings and the three autonomy zones, so a SpecForge `tasks.md` fails it by construction; this needs a converter and a second validation path, not another entry in the genre table. It is in the [Roadmap](#roadmap) as such, and it is a plan, not a feature.

## Acknowledgments

Autonomy zones and error budget inspired by [AlpiType — Solving the AI Agent Approval Loop](https://alpitype.de/insights/ki-agenten-approval-loop/)

## Disclaimer

This project was created privately, to the best of the author's knowledge. Use at your own risk. No warranty of completeness, correctness, or fitness for any particular purpose.

## License

Apache-2.0 — see [LICENSE](LICENSE)
