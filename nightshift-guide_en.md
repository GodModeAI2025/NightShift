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
- [ ] **macOS** recommended (for kernel-level sandbox). Linux works without the sandbox — use Docker instead.

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

Download the skill from the repository:

```bash
# Option A: Download the .skill file
curl -L https://github.com/GodModeAI2025/NightShift/raw/main/nightshift/SKILL.md -o /tmp/nightshift-skill.md

# Create the skill directory
mkdir -p ~/.claude/skills/nightshift/scripts

# Copy files
cp /tmp/nightshift-skill.md ~/.claude/skills/nightshift/SKILL.md
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

If validation fails, Claude suggests fixes. The setup is only generated when all checks pass.

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

**With sandbox (recommended on macOS):**
```bash
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh
```

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
```

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
Every headless run consumes API credits. A typical overnight run costs $5–50 depending on complexity. Monitor at console.anthropic.com.

### The Sandbox Must Be Activated Explicitly
The sandbox file exists, but you must start with `sandbox-exec -f ...` to activate it. Without it, Claude has full access to your user account.

### Runbook Quality = Result Quality
Vague steps produce vague results. Review the runbook before starting. If you need more than 20 steps, split into multiple runs.

### Context Compression
On runs longer than 20 minutes, context compression happens. The hooks handle it, but for 30+ step runbooks, quality degrades. Stay under 20 steps per run.

### Linux Users
`sandbox-exec` is macOS only. Use Docker or a dedicated user account:
```bash
sudo useradd -m clauderunner
sudo cp -r /your/project /home/clauderunner/project
sudo -u clauderunner ./nightshift-run.sh
```

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
