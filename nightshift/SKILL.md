---
name: nightshift
license: Apache-2.0
compatibility: "Requires Claude Code CLI (claude -p), bash, python3, jq. macOS recommended for sandbox-exec."
description: "Generates a complete autonomous Claude Code setup as ZIP from a project path and task description. Includes a validated runbook with genre templates, security hooks, heartbeat watchdog, and macOS sandbox profile. Use this skill whenever someone wants to run Claude Code autonomously, overnight, or unattended. Also use for headless Claude Code, dangerously-skip-permissions setup, autonomous agent runs, or batch project work. Trigger phrases: Nachtlauf, Nightshift, autonom arbeiten, über Nacht, YOLO mode einrichten, Claude absichern, Runbook erstellen."
---

# Claude Nightshift

Generates a complete autonomous Claude Code setup as ZIP — validated runbook, security hooks, heartbeat watchdog, and optional macOS sandbox. The user provides a project path and a task description; the skill produces everything needed to let Claude Code work unattended.

## Why this exists

Running Claude Code with `--dangerously-skip-permissions` alone breaks down after ~20 minutes: context gets compacted, Claude forgets the plan, repeats steps, or drifts. Nightshift solves this with four layers: a validated runbook as external memory, a compact-recovery hook that re-injects the plan, security hooks that block destructive commands, and a watchdog that monitors liveness.

## Input

$ARGUMENTS — interpret as:

| Input | Action |
|-------|--------|
| *(empty)* | Interactive: ask for project path, task, genre |
| `[path] [task]` | Direct: auto-detect genre, confirm with user |
| `genre list` | Show all 8 genre templates with phases |
| `validate [path/runbook.md]` | Validate an existing runbook |

## Workflow

### Step 1: Gather input

Ask the user for:
1. **Project path** — absolute path to the project directory
2. **Task** — what Claude should accomplish
3. **Stack info** (optional) — auto-detect from package.json, Cargo.toml, pyproject.toml if available

### Step 2: Select genre

Suggest the most fitting genre based on the task description. Confirm with the user (use `ask_user_input` if available). Each genre provides a phase template and risk checks.

**Available genres:** refactoring (5 phases), feature (6 phases), migration (5 phases), bugfix (5 phases), testing (4 phases), cleanup (4 phases), devops (4 phases), documentation (4 phases)

Genre details and phase definitions are embedded in `scripts/build_zip.py` under `GENRE_TEMPLATES`.

### Step 3: Generate runbook

Fill the genre template with concrete, project-specific steps. Every step needs at least one of: a file path, a shell command, or a concrete action with function/class names. Vague steps like "implement auth" cause Claude to guess — and guessing in headless mode means wasted API calls or broken code.

**Example of a good step:**
```
- [ ] Create src/services/token-service.ts with: generateAccessToken(userId), verifyToken(token)
```

**Example of a bad step:**
```
- [ ] Implement the auth module
```

### Step 3b: Add autonomy zones

Every runbook gets a section that tells Claude what it may do freely, what it should log, and what is forbidden. This prevents two failure modes: Claude hesitating on trivial operations (too cautious) and Claude overreaching on critical files (too aggressive).

```markdown
### Autonomiebereiche
🟢 Frei (ohne Rückfrage, ohne Protokoll):
- Dateien lesen
- Dateien erstellen/ändern in src/, tests/, docs/
- Dependencies installieren
- Tests ausführen
- Git add + commit

🟡 Protokollpflichtig (in log.md dokumentieren warum):
- Dateien löschen
- Konfigurationsdateien ändern (.env.example, tsconfig, etc.)
- Mehr als 3 Dateien in einem Schritt ändern
- Dependency-Major-Upgrades

🔴 Verboten (auch mit skip-permissions):
- Dateien außerhalb des Projektordners
- Secrets/Credentials/API-Keys anfassen
- Produktionsdatenbank schreiben
- Force-Push
```

Adapt the zones to the project. A devops genre needs more freedom for config files; a documentation genre can restrict write access to docs/ only.

### Step 3c: Define error budget

Without an error budget, Claude either stops at the first failing test (wasting the whole run) or ignores real regressions. Define explicit thresholds:

```markdown
### Fehler-Toleranz
- 1 fehlschlagender Test: Fix versuchen, max. 2 Versuche, dann weiter
- 2-3 fehlschlagende Tests: Warnung in log.md, Phase abschließen
- Über 3 fehlschlagende Tests: STOPPEN, Zustand sichern, log.md schreiben
- Linter-Warnings: Ignorieren, nur Errors zählen
```

Adapt thresholds to the project. A testing genre needs stricter budgets; a cleanup genre can be more lenient.

### Step 4: Validate runbook

Run the 15-point validation (structure, quality, safety, genre-check, autonomy zones, error budget). Show results to the user. Only generate the ZIP once validation passes — or when the user explicitly overrides.

The validation catches: missing rollback section, vague steps, steps targeting paths outside the project, hardcoded secrets, `rm -rf` in step text, too many or too few steps, missing autonomy zones, missing error budget.

### Step 5: Generate ZIP

Copy and configure the build script:

```bash
cp /mnt/skills/user/nightshift/scripts/build_zip.py /home/claude/build_nightshift.py
```

Set variables directly in the script OR pass as environment variables:
- `PROJEKTPFAD` — absolute project path (or `export NIGHTSHIFT_PROJECT=/path`)
- `AUFGABE_TITEL` — task title
- `AUFGABE_KURZ` — short title for git commit message
- `TESTBEFEHL` — test command from stack detection
- `STACK_INFO` — detected technologies
- `GENRE` — selected genre
- `RUNBOOK` — the validated runbook text (the core content)

```bash
python3 /home/claude/build_nightshift.py
```

### Step 6: Present output

1. Present the ZIP with `present_files`
2. Show a short installation guide with concrete paths
3. Show runbook summary: genre, step count, phases

## Generated files

The ZIP contains:

| File | Purpose |
|------|---------|
| runbook.md | Task plan with checkboxes — Claude's external memory |
| .claude/settings.json | Hooks: PreToolUse (security), PostToolUse (heartbeat), SessionStart (compact recovery), Stop (checkpoint every 5 steps) |
| nightshift-run.sh | Main script: headless mode + skip-permissions + PID lock + graceful shutdown |
| nightshift-run-bg.sh | Background starter (nohup) |
| nightshift-watchdog.sh | Heartbeat monitor with macOS notification support |
| nightshift-sandbox.sb | macOS sandbox profile — restricts filesystem to project + /tmp |
| CLAUDE-nightshift.md | Append to CLAUDE.md for project conventions |
| README-nightshift.md | Full installation and usage guide |

## Error handling

| Situation | Action |
|-----------|--------|
| No git repo | Warn that rollback is limited. Adjust runbook rollback section. |
| No test command detected | Ask user. Fall back to echo placeholder and flag in validation. |
| .claude/settings.json exists | Read existing file, merge hooks — never overwrite. |
| CLAUDE.md exists | Append nightshift section — never overwrite. |
| Project path missing | Ask again. |
| More than 20 steps needed | Suggest splitting into 2 nightshift runs. |

## Security

- PreToolUse hook blocks: rm -rf, mkfs, dd, sudo, chmod 777, curl-pipe-bash, eval, fork bombs
- Sandbox profile restricts filesystem access to project directory + /tmp at kernel level
- PID lock prevents duplicate runner instances
- Always recommend sandbox; warn when using skip-permissions without it
- Cost warning displayed at runner startup — headless runs consume API credits without supervision
