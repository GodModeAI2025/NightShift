# Nightshift — Training Guide

> Let Claude Code work autonomously overnight on your project.

**Skill Repository:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Landing Page:** [godmodeai2025.github.io/NightShift](https://godmodeai2025.github.io/NightShift/)

---

## What You Will Learn

After this guide, you will be able to:

1. Install the Nightshift skill into Claude Code
2. Generate a validated runbook for any project task
3. Start an autonomous overnight run with security hooks and sandbox
4. Monitor the run with the heartbeat watchdog
5. Review results and roll back if needed

---

## Prerequisites

Before you start, make sure you have:

- [ ] **Claude Code CLI** installed and authenticated (type `claude` in your terminal — if it opens, you're good)
- [ ] **bash**, **python3** (3.9 or newer), and **jq** in your PATH
- [ ] **A git repository** with your project (you need git for rollback)
- [ ] **Docker** with Compose v2 for the default run. Same on Linux and macOS. Plus an `ANTHROPIC_API_KEY`, because the container has its own home.
- [ ] Optionally **macOS** with `sandbox-exec`, if Docker is not available.

---

## Lesson 1: Understanding the Problem

Open your terminal and start Claude Code on a project:

```bash
cd /your/project
claude
```

Ask Claude to do something complex, like refactoring a module. Watch what happens:

1. Claude asks for permission to read a file → you press Enter
2. Claude asks for permission to write a file → you press Enter
3. Claude asks for permission to run a test → you press Enter
4. Repeat 40 times per hour

Now imagine this running overnight. It can't — because Claude stops and waits for your approval every time.

The flag `--dangerously-skip-permissions` removes all approval prompts. But without guardrails, Claude has full access to your entire system. Documented incidents include deleting home directories.

**Nightshift solves this:** It wraps `--dangerously-skip-permissions` in four layers of protection so Claude can work safely without you.

---

## Lesson 2: Install the Skill

Download the skill from the latest release:

```bash
mkdir -p ~/.claude/skills
curl -LO https://github.com/GodModeAI2025/NightShift/releases/latest/download/nightshift.skill
unzip nightshift.skill -d ~/.claude/skills/
```

`nightshift.skill` is a ZIP archive. It unpacks to `~/.claude/skills/nightshift/` with `SKILL.md`, `scripts/build_zip.py`, the license, and a `VERSION` file.

If the download returns 404, no version has been tagged yet. Take the files from `main` in that case:

```bash
mkdir -p ~/.claude/skills/nightshift/scripts
curl -L https://github.com/GodModeAI2025/NightShift/raw/main/nightshift/SKILL.md -o ~/.claude/skills/nightshift/SKILL.md
curl -L https://github.com/GodModeAI2025/NightShift/raw/main/nightshift/scripts/build_zip.py -o ~/.claude/skills/nightshift/scripts/build_zip.py
```

**Verify:** Open Claude Code and type: "Set up a nightshift run for /tmp/test-project — add a README". If Claude responds with genre selection and runbook generation, the skill is installed correctly.

---

## Lesson 3: Generate Your First Setup

Tell Claude your project and task:

```
Set up a nightshift run for /Users/me/projects/my-api — migrate the auth module from sessions to JWT tokens
```

Claude will walk you through:

### 3.1 Genre Selection

Claude detects the task type and suggests a genre. In this case: **migration**. Confirm or choose a different one. Each genre has predefined phases:

| Genre | Phases |
|-------|--------|
| migration | Compatibility check → Parallel run → Stepwise migration → Verify → Remove old |
| refactoring | Analysis → Test coverage → Restructure → Verify → Cleanup |
| feature | Prep → Structure → Core logic → Integration → Tests → Cleanup |

### 3.2 Runbook Generation

Claude creates a runbook with concrete steps. Review it carefully — **this is what Claude will execute overnight**. Every step should contain:

- A file path: `src/services/token-service.ts`
- A command: `bun add jsonwebtoken`
- A concrete action: `Create function generateAccessToken(userId: string)`

**Bad step:** `Implement JWT auth` — too vague, Claude will guess.
**Good step:** `Create src/services/token-service.ts with functions generateAccessToken(userId), verifyToken(token), refreshToken(token)`

### 3.3 Validation

Claude validates the runbook against 15 checks:

- Structure: Preconditions, verification phase, rollback instructions present?
- Quality: Every step concrete enough? No vague formulations?
- Safety: No `rm -rf`? No hardcoded secrets? All paths inside project?
- Autonomy: Three zones (green/yellow/red) defined? Error budget with stop condition?

If validation fails, Claude suggests fixes. The generator writes the ZIP either way, so a failed check is a prompt to fix the runbook, not a stop.

### 3.4 Setup Files

Claude generates these files:

| File | What It Does |
|------|-------------|
| `runbook.md` | Your task plan — Claude's external memory |
| `.claude/settings.json` | Security hooks, heartbeat, compact recovery, checkpoint repetition |
| `nightshift-run.sh` | The main runner script |
| `nightshift-watchdog.sh` | Heartbeat monitor |
| `nightshift-sandbox.sb` | macOS kernel sandbox profile |

---

## Lesson 4: Install and Run

### 4.1 Copy Files

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

**If `.claude/settings.json` already exists**, merge instead of copying. The
command keeps your own hooks, permissions, and MCP settings and appends the
Nightshift hooks per event type:

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

### 4.2 Commit First (Critical!)

```bash
git add -A && git commit -m "Checkpoint before Nightshift"
```

This is your undo button. Without it, there is no rollback.

### 4.3 Start

**In the container (the default):**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
./nightshift-docker.sh
```
Builds both images, mounts only the project as `/project`, runs the night, tears the containers down. Budget: 25 USD, `NIGHTSHIFT_BUDGET_USD=5 ./nightshift-docker.sh` for a single run.

**With the seatbelt profile (macOS option):**
```bash
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh
```

No environment variable is involved: the runner probes whether it really sits behind the profile. Under the profile it can list the project but not `/Users`, and that is what produces the `seatbelt` state.

A plain `./nightshift-run.sh` aborts with exit code 3. To run without isolation on purpose, set `NIGHTSHIFT_ALLOW_UNSANDBOXED=1`; the receipt then says `keine`. `NIGHTSHIFT_SANDBOXED` is a cross-check only: if its value disagrees with the measurement, the run aborts with 3. Any word at all used to be enough to pass this check.

**Background (terminal can be closed):**
```bash
./nightshift-run-bg.sh
```

**What happens now:**
1. Claude starts in headless mode (`claude -p`)
2. Reads `runbook.md` for the task plan
3. Works through steps, checking off completed items
4. Every tool call triggers a heartbeat
5. After context compression, the hook says "re-read runbook.md"
6. Every 5 completed steps, autonomy zones and error budget are repeated
7. At the end, Claude commits the changes

### 4.4 Monitor (Optional)

In a second terminal:

```bash
./nightshift-watchdog.sh          # Alert after 10 min without heartbeat
./nightshift-watchdog.sh 300      # Alert after 5 min

# React instead of only reporting:
NIGHTSHIFT_WATCHDOG_AKTION=beenden ./nightshift-watchdog.sh 600
NIGHTSHIFT_WATCHDOG_AKTION=neustart ./nightshift-watchdog.sh 600
```

`beenden` sends TERM to the run and KILL 20 seconds later. `neustart` does the same and then starts the run again, once by default (`NIGHTSHIFT_WATCHDOG_NEUSTARTS`). Only a run the watchdog just terminated itself gets restarted: a run that ended on its own has no live PID any more, and a budget stop looks exactly like that. What the watchdog does not see is a loop in which Claude runs the same failing test over and over, because the heartbeat stays green through it.

---

## Lesson 5: Review Results

In the morning:

```bash
# What did Claude commit?
git log --oneline -5

# What changed?
git diff HEAD~1

# Which steps were completed?
cat runbook.md | grep "\[x\]"

# Which steps were NOT completed?
cat runbook.md | grep "\[ \]"
```

### If Something Went Wrong

```bash
# Undo everything
git checkout .

# Or save changes for review
git stash

# Kill the process if still running
pkill -f "claude.*dangerously"
```

---

## Lesson 6: What to Watch Out For

### API Costs
Every headless run consumes API credits. Nightshift counts them: `nightshift-cost.sh` sums the usage fields from the stream-json output, estimates the dollars from a dated price table and at the budget kills Claude's process group with exit code 9. Measured against a real run, the estimate came to 0.25860 USD where Claude itself reported 0.25863 USD for the same request. A model the table does not know is billed at twice the most expensive known row — a newer model can cost more than anything in the table. If the stream carries no usage events at all, a changed output format for instance, the counter writes `unbekannt` and not a zero. The figure in the receipt remains an estimate; the invoice is at console.anthropic.com.

### A Run Without Isolation Aborts
`nightshift-run.sh` checks how it is fenced before it calls Claude: container, seatbelt or nothing. On nothing, the run ends with exit code 3. `NIGHTSHIFT_ALLOW_UNSANDBOXED=1` is the deliberate way past it.

### The Morning Receipt
After every run, `nightshift-receipts/<run>/receipt.json` and `receipt.md` sit in the project, including after a crash. Fields the run could not determine read `unbekannt`, not 0.

### Runbook Quality = Result Quality
Vague steps produce vague results. Review the runbook before starting. If you need more than 20 steps, split into multiple runs.

### Context Compression
On runs longer than 20 minutes, context compression happens. The hooks handle it, but for 30+ step runbooks, quality degrades. Stay under 20 steps per run.

### Linux Users
`sandbox-exec` is macOS only, and it is no longer needed: `./nightshift-docker.sh` is the same route on both systems and the sharper boundary, because reads and outbound traffic are fenced too.

Without Docker, a dedicated user account remains the weaker fallback:
```bash
sudo useradd -m clauderunner
sudo cp -r /your/project /home/clauderunner/project
sudo chown -R clauderunner: /home/clauderunner/project
sudo -u clauderunner env NIGHTSHIFT_PROJEKT=/home/clauderunner/project \
    NIGHTSHIFT_ALLOW_UNSANDBOXED=1 \
    bash /home/clauderunner/project/nightshift-run.sh
```
Without the `chown`, the copy belongs to root and the runner cannot write in its own working directory. `NIGHTSHIFT_PROJEKT` moves the run into the copy; without it, the run lands back in the original directory. The new account needs its own Claude Code login. It still reaches the network and reads every world-readable file, which is why the run needs the explicit opt-out.

---

## Practice Exercise

Try this on a test project:

1. Create a small Node.js project: `mkdir /tmp/nightshift-test && cd /tmp/nightshift-test && npm init -y && git init && git add -A && git commit -m "init"`
2. Install the Nightshift skill
3. Tell Claude: "Set up a nightshift run for /tmp/nightshift-test — add a comprehensive README with installation, usage, and API docs based on package.json"
4. Review the generated runbook
5. Run it (foreground, without sandbox since it's a test project)
6. Check the result

---

**Source code:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Impressum:** [godmodeai2025.github.io/MarkZimmermann](https://godmodeai2025.github.io/MarkZimmermann/)
