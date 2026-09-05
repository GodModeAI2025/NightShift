#!/usr/bin/env python3
"""
Claude 24x7 — ZIP Builder
Erzeugt einen endlosen Runner mit Inbox/Outbox-Architektur
"""

import json, os, re, sys, zipfile
from datetime import datetime

# Die Schutzschicht steht in gemeinsam.py, damit beide Skills dieselbe haben
# und nicht zwei Kopien auseinanderlaufen. Im Repo liegt die Datei im
# Wurzelverzeichnis, im installierten Skill neben diesem Skript; gesucht wird
# an beiden Stellen. Bytecode wird nicht geschrieben, sonst legt der Skill
# beim ersten Lauf ein __pycache__ in ~/.claude/skills ab.
sys.dont_write_bytecode = True
_HIER = os.path.dirname(os.path.abspath(__file__))
for _ort in (_HIER, os.path.dirname(os.path.dirname(_HIER))):
    if os.path.isfile(os.path.join(_ort, "gemeinsam.py")):
        sys.path.insert(0, _ort)
        break
else:
    raise SystemExit(
        "ERROR: gemeinsam.py nicht gefunden. Erwartet neben diesem Skript "
        "oder im Wurzelverzeichnis des Repos."
    )
import gemeinsam

# ╔══════════════════════════════════════════════════════════╗
# ║  VARIABLEN ANPASSEN                                     ║
# ╚══════════════════════════════════════════════════════════╝

WORKSPACE = os.environ.get("CLAUDE_24X7_WORKSPACE", "REPLACE_ME")
if WORKSPACE == "REPLACE_ME":
    raise SystemExit("ERROR: Set WORKSPACE before running, or export CLAUDE_24X7_WORKSPACE=/your/workspace")
HOMEDIR = os.path.expanduser("~")
POLL_INTERVAL = 30          # Sekunden zwischen Inbox-Checks
MAX_TASK_MINUTES = 60       # Timeout pro Task
IDLE_TIMEOUT_MINUTES = 15   # Timeout für Idle-Tasks
IDLE_BEHAVIOR = "cleanup"   # cleanup | docs | tests | sleep

# Wohin der Container nach draussen darf. Alles andere beantwortet der
# Proxy mit 403.
NETZ_ALLOWLIST = ["api.anthropic.com"]
NETZ_ALLOWLIST_TEXT = ", ".join("`%s`" % host for host in NETZ_ALLOWLIST)

# ════════════════════════════════════════════════════════════
#  AB HIER NICHTS ÄNDERN
# ════════════════════════════════════════════════════════════

CLAUDE_MD = f"""# Claude 24x7 Workspace

## Regeln
- Du bearbeitest genau EINEN Task pro Session
- Lies task.md im Arbeitsordner für den Auftrag
- Materialien liegen in materials/
- Ergebnisse kommen nach output/
- Erstelle eine log.md mit einer kurzen Zusammenfassung was du getan hast
- Arbeite NUR im Arbeitsordner, NICHT außerhalb des Workspace
- NIEMALS Pfade außerhalb von {WORKSPACE} lesen oder schreiben
- Wenn du fertig bist, beende die Session sauber

## Autonomiebereiche
Grün — Frei:
- Dateien in materials/ lesen
- Dateien in output/ erstellen und ändern
- log.md erstellen und aktualisieren

Gelb — Protokollpflichtig (in log.md dokumentieren):
- Dateien löschen
- Mehr als 5 Dateien in output/ erstellen
- Shell-Befehle die nicht im Auftrag stehen

Rot — Verboten:
- Pfade außerhalb des Arbeitsordners
- Secrets/Credentials/API-Keys in output/ schreiben
- sudo, rm -rf, chmod 777
- Netzwerk-Calls die nicht im Auftrag stehen

## Fehler-Toleranz
- Kleiner Fehler: Protokollieren, weitermachen
- Input-Datei nicht lesbar: In log.md melden, Task trotzdem abschließen
- Auftrag unklar: Beste Interpretation wählen, in log.md begründen
- Schwerer Fehler (Crash, Dependency fehlt): log.md schreiben, Session beenden

## Idle-Verhalten: {IDLE_BEHAVIOR}
Wenn du als Idle-Task gestartet wirst, halte dich an idle/idle-tasks.md

## Workspace-Gedaechtnis
- Lies `{WORKSPACE}/decisions.md` am Anfang jedes Tasks falls vorhanden
- Die Datei enthaelt Entscheidungen und Erkenntnisse aus vorherigen Tasks
- Schreibe eigene relevante Entscheidungen am Ende deines Tasks dazu (append, nicht ueberschreiben)
- Format: Datum, Task-Name, Entscheidung, Begruendung
- Nur Entscheidungen dokumentieren die fuer andere Tasks relevant sein koennten
"""

IDLE_TASKS = {
    "cleanup": """## Idle-Aufgaben (wenn keine Tasks warten)

### Was tun bei Leerlauf
1. Prüfe ob im Workspace Dateien aufgeräumt werden können
2. Suche nach TODO-Kommentaren in Dateien unter outbox/ und erstelle eine todo-sammlung.md
3. Prüfe ob task.md Dateien in outbox/ vollständig bearbeitet wurden
4. Erstelle eine Zusammenfassung aller erledigten Tasks als daily-report.md im Workspace-Root

### Regeln
- Nichts löschen
- Nichts außerhalb des Workspace anfassen
- Ergebnisse in output/ des idle-Ordners ablegen
- Maximal 15 Minuten arbeiten
""",
    "docs": """## Idle-Aufgaben (wenn keine Tasks warten)

### Was tun bei Leerlauf
1. Lies die erledigten Tasks in outbox/
2. Erstelle oder aktualisiere eine README.md im Workspace mit einer Übersicht aller bearbeiteten Aufgaben
3. Fasse Muster zusammen: Welche Arten von Tasks kommen häufig? Was könnte verbessert werden?

### Regeln
- Ergebnisse in output/ des idle-Ordners ablegen
- Maximal 15 Minuten arbeiten
""",
    "tests": """## Idle-Aufgaben (wenn keine Tasks warten)

### Was tun bei Leerlauf
1. Schau in outbox/ nach Code-Dateien in output/ Ordnern
2. Prüfe ob Tests vorhanden sind
3. Wenn nicht: Erstelle Test-Vorschläge als test-suggestions.md

### Regeln
- Keine Dateien in outbox/ verändern
- Ergebnisse in output/ des idle-Ordners ablegen
- Maximal 15 Minuten arbeiten
""",
    "sleep": """## Idle-Aufgaben (wenn keine Tasks warten)

### Was tun bei Leerlauf
Nichts. Session sofort beenden.
"""
}

# ── PreToolUse-Hooks: rote Zone ─────────────────────────────
# Zwei Schranken, beide aus gemeinsam.py:
#   Bash                              prueft den Kommandotext
#   Write, Edit, MultiEdit, NotebookEdit  prueft den Zielpfad
# CLAUDE.md verlangt seit jeher "NIEMALS Pfade ausserhalb des Workspace
# schreiben". Bis Welle 6 war das eine Bitte an das Modell; die Pfadschranke
# macht die Schreibhaelfte davon zu einer Regel, die auch dann greift, wenn
# das Modell sie vergisst.
PRETOOLUSE = gemeinsam.pretooluse(
    "24x7", "CLAUDE_24X7_WORKSPACE", WORKSPACE
)


SETTINGS = {
    "hooks": {
        "PreToolUse": PRETOOLUSE,
        "PostToolUse": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": "bash -c 'echo \"$(date -Iseconds) heartbeat\" >> /tmp/24x7-heartbeat.log'",
                    }
                ],
            }
        ],
    }
}

# ── Container und Isolation: Gehaeuse aus gemeinsam.py ──────
# Bis Welle 6 gab es beides nur fuer Nightshift. Die Vorlagen stehen in
# gemeinsam.py, hier stehen nur die Namen. Der Workspace liegt im Container
# unter /workspace, nicht unter dem Pfad, der beim Generieren gesetzt war.
_NAMEN = {
    "TITEL": "24x7",
    "MOUNT": "/workspace",
    "DOCKERSKRIPT": "24x7-docker.sh",
    "STARTSKRIPT": "runner.sh",
    "SANDBOXVAR": "CLAUDE_24X7_SANDBOXED",
    "ALLOWVAR": "CLAUDE_24X7_ALLOW_UNSANDBOXED",
    "PFADVAR": "CLAUDE_24X7_WORKSPACE",
    "PROFILNAME": "24x7",
    "PROFILDATEI": "sandbox.sb",
    "GEGENSTAND": "der Workspace",
    "GEGENSTAND_AKK": "den Workspace",
    "PFADSHELL": "WORKSPACE",
    "DIENST": "24x7",
    "HOSTPFAD": WORKSPACE,
    "SPEICHER": "4g",
    "READMENAME": "README.md",
    "ZWECK": "Baut den Container und laesst den 24x7-Runner darin laufen.",
    "KOPF": "24x7, isoliert. Der Standardweg auf Linux und macOS.",
    "WERKZEUGNOTIZ": (
        "# coreutils bringt timeout mit, das der Runner fuer den Task-Deckel\n"
        "# braucht und das ein nacktes macOS nicht hat."
    ),
    "ALLOWLIST": gemeinsam.allowlist_argumente(NETZ_ALLOWLIST),
    "ZUSATZENV": "",
    "HOME": HOMEDIR,
    "FREIGABENAME": "Workspace-Freigabe",
}

DOCKER_LOGS = "docker compose logs -f 24x7"

DOCKERFILE = gemeinsam.dockerfile(_NAMEN)
DOCKER_COMPOSE = gemeinsam.compose(_NAMEN)
DOCKER_SH = gemeinsam.docker_sh(_NAMEN, gemeinsam.DOCKER_SH_DAEMON)

RUNNER_SH = f"""#!/bin/bash
set -uo pipefail

WORKSPACE="${{CLAUDE_24X7_WORKSPACE:-{WORKSPACE}}}"
INBOX="$WORKSPACE/inbox"
WORKING="$WORKSPACE/working"
OUTBOX="$WORKSPACE/outbox"
FAILED="$WORKSPACE/failed"
IDLE="$WORKSPACE/idle"
POLL={POLL_INTERVAL}
MAX_SECONDS={MAX_TASK_MINUTES * 60}
IDLE_SECONDS={IDLE_TIMEOUT_MINUTES * 60}
LOGFILE="/tmp/24x7-$(date +%Y%m%d).log"

# Timeout-Kommando bestimmen. Ohne Timeout laeuft ein haengender Task
# unbegrenzt weiter, deshalb Abbruch statt stillem Weiterlaufen.
# macOS bringt kein timeout mit; coreutils installiert es als gtimeout.
if command -v timeout >/dev/null 2>&1; then
    TIMEOUT_BIN="timeout"
elif command -v gtimeout >/dev/null 2>&1; then
    TIMEOUT_BIN="gtimeout"
else
    echo "❌ Weder 'timeout' noch 'gtimeout' gefunden."
    echo "   Der Runner braucht eins von beiden, um Tasks zu deckeln."
    echo "   macOS: brew install coreutils (liefert gtimeout)"
    echo "   Linux: Paket coreutils installieren"
    exit 1
fi

@@ISOLATION_MESSEN@@
@@ISOLATION_ABBRUCH@@
# Beides steht vor dem PID-Lock und vor der trap-Zeile. cleanup endet
# mit exit 0, und ein Abbruch dahinter kaeme als 0 beim Aufrufer an.

# PID-Lock: Verhindert doppelten Start
PIDFILE="/tmp/24x7.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "❌ 24x7 Runner läuft bereits (PID $(cat "$PIDFILE"))"
    echo "   Beenden: kill $(cat "$PIDFILE")"
    exit 1
fi
echo $$ > "$PIDFILE"

# Graceful Shutdown
cleanup() {{
    echo ""
    echo "⏹  24x7 Runner wird beendet... ($(date))" | tee -a "$LOGFILE"
    # Laufenden Task in working/ nach failed/ verschieben
    for DIR in "$WORKING"/*/; do
        [ -d "$DIR" ] || continue
        TASK_NAME=$(basename "$DIR")
        echo "   ⚠️  Task '$TASK_NAME' war in Bearbeitung → failed/" | tee -a "$LOGFILE"
        echo "ABBRUCH: Runner wurde beendet" >> "$DIR/log.md" 2>/dev/null
        mv "$DIR" "$FAILED/$TASK_NAME" 2>/dev/null
    done
    rm -f "$PIDFILE"
    exit 0
}}
trap cleanup SIGTERM SIGINT EXIT

# Ordner anlegen
mkdir -p "$INBOX" "$WORKING" "$OUTBOX" "$FAILED" "$IDLE"

echo "============================================" | tee -a "$LOGFILE"
echo "  Claude 24x7 Runner gestartet: $(date)" | tee -a "$LOGFILE"
echo "  Workspace: $WORKSPACE" | tee -a "$LOGFILE"
echo "  Poll-Intervall: ${{POLL}}s" | tee -a "$LOGFILE"
echo "  Task-Timeout: {MAX_TASK_MINUTES} Min (via $TIMEOUT_BIN)" | tee -a "$LOGFILE"
echo "  Idle: {IDLE_BEHAVIOR}" | tee -a "$LOGFILE"
echo "  Isolation: $ISOLATION" | tee -a "$LOGFILE"
echo "  Log: $LOGFILE" | tee -a "$LOGFILE"
echo "  PID: $$" | tee -a "$LOGFILE"
echo "============================================" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"
echo "⚠️  KOSTEN-HINWEIS: 24x7 erzeugt kontinuierlich API-Calls!" | tee -a "$LOGFILE"
echo "   Überwache dein Anthropic-Dashboard." | tee -a "$LOGFILE"
echo "   Idle auf 'sleep' setzen wenn Kosten ein Thema sind." | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

# Heartbeat zurücksetzen
> /tmp/24x7-heartbeat.log

TASK_COUNT=0

while true; do
  # Finde ältesten Task-Ordner mit task.md
  TASK_DIR=""
  OLDEST=""

  for DIR in "$INBOX"/*/; do
    [ -d "$DIR" ] || continue
    [ -f "$DIR/task.md" ] || continue
    if [ -z "$OLDEST" ] || [ "$DIR" -ot "$OLDEST" ]; then
      OLDEST="$DIR"
    fi
  done

  if [ -n "$OLDEST" ]; then
    TASK_NAME=$(basename "$OLDEST")
    TASK_COUNT=$((TASK_COUNT + 1))

    echo "📋 [$TASK_COUNT] Task gefunden: $TASK_NAME ($(date +%H:%M:%S))" | tee -a "$LOGFILE"

    # In working/ verschieben
    mv "$OLDEST" "$WORKING/$TASK_NAME"
    mkdir -p "$WORKING/$TASK_NAME/output"

    # Task-Inhalt lesen für Prompt
    TASK_CONTENT=$(cat "$WORKING/$TASK_NAME/task.md")

    # Claude starten mit Timeout
    echo "   ▶ Claude startet..." | tee -a "$LOGFILE"
    "$TIMEOUT_BIN" $MAX_SECONDS claude -p \\
      "Du bearbeitest folgenden Task im Ordner $WORKING/$TASK_NAME.

AUFTRAG (aus task.md):
$TASK_CONTENT

REGELN:
- Materialien liegen in $WORKING/$TASK_NAME/materials/
- Ergebnisse NUR in $WORKING/$TASK_NAME/output/ ablegen
- Erstelle $WORKING/$TASK_NAME/log.md mit Zusammenfassung
- Lies $WORKSPACE/decisions.md falls vorhanden (Entscheidungen vorheriger Tasks)
- Schreibe relevante eigene Entscheidungen an $WORKSPACE/decisions.md an (append)
- Arbeite NUR in diesem Ordner
- Wenn fertig: Session beenden" \\
      --dangerously-skip-permissions \\
      --output-format stream-json \\
      --verbose \\
      >> "$LOGFILE" 2>&1

    EXIT_CODE=$?

    if [ $EXIT_CODE -eq 0 ]; then
      # Erfolg → outbox
      mv "$WORKING/$TASK_NAME" "$OUTBOX/$TASK_NAME"
      echo "   ✅ Erledigt → outbox/$TASK_NAME ($(date +%H:%M:%S))" | tee -a "$LOGFILE"
    elif [ $EXIT_CODE -eq 124 ]; then
      # Timeout
      echo "TIMEOUT" > "$WORKING/$TASK_NAME/log.md"
      mv "$WORKING/$TASK_NAME" "$FAILED/$TASK_NAME"
      echo "   ⏰ Timeout nach {MAX_TASK_MINUTES} Min → failed/$TASK_NAME" | tee -a "$LOGFILE"
    else
      # Fehler
      echo "EXIT CODE: $EXIT_CODE" >> "$WORKING/$TASK_NAME/log.md" 2>/dev/null
      mv "$WORKING/$TASK_NAME" "$FAILED/$TASK_NAME"
      echo "   ❌ Fehler (Exit $EXIT_CODE) → failed/$TASK_NAME" | tee -a "$LOGFILE"
    fi

    echo "" | tee -a "$LOGFILE"

  else
    # Keine Tasks → Idle
    echo "💤 Keine Tasks. Idle-Modus... ($(date +%H:%M:%S))" | tee -a "$LOGFILE"

    IDLE_DIR="$WORKING/idle-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$IDLE_DIR/output"
    cp "$IDLE/idle-tasks.md" "$IDLE_DIR/task.md" 2>/dev/null

    if [ -f "$IDLE_DIR/task.md" ] && ! grep -q "Session sofort beenden" "$IDLE_DIR/task.md"; then
      "$TIMEOUT_BIN" $IDLE_SECONDS claude -p \\
        "Du bist im Idle-Modus. Lies $IDLE_DIR/task.md und arbeite die Idle-Aufgaben ab.
Ergebnisse in $IDLE_DIR/output/ ablegen.
Workspace-Root ist $WORKSPACE.
Wenn fertig: Session beenden." \\
        --dangerously-skip-permissions \\
        --output-format stream-json \\
        --verbose \\
        >> "$LOGFILE" 2>&1

      if [ -d "$IDLE_DIR" ] && [ "$(ls -A "$IDLE_DIR/output/" 2>/dev/null)" ]; then
        mv "$IDLE_DIR" "$OUTBOX/"
        echo "   📝 Idle-Ergebnis → outbox/" | tee -a "$LOGFILE"
      else
        rm -rf "$IDLE_DIR"
      fi
    else
      rm -rf "$IDLE_DIR"
    fi

    # Warten bis nächster Check
    echo "   ⏳ Nächster Check in ${{POLL}}s..." | tee -a "$LOGFILE"
    sleep $POLL
  fi
done
""".replace(
    "@@ISOLATION_MESSEN@@", gemeinsam.isolation_messen(_NAMEN)
).replace(
    "@@ISOLATION_ABBRUCH@@", gemeinsam.isolation_abbruch(_NAMEN)
)

RUNNER_BG_SH = f"""#!/bin/bash
echo "Starte Claude 24x7 im Hintergrund..."
WORKSPACE="${{CLAUDE_24X7_WORKSPACE:-{WORKSPACE}}}"
nohup bash "$WORKSPACE/runner.sh" > /tmp/24x7-nohup.log 2>&1 &
PID=$!
echo ""
echo "  PID:      $PID"
echo "  Log:      /tmp/24x7-$(date +%Y%m%d).log"
echo "  Nohup:    /tmp/24x7-nohup.log"
echo "  Watchdog: ./watchdog.sh"
echo "  Stoppen:  kill $PID"
echo ""
echo "Task einwerfen:"
echo "  mkdir -p {WORKSPACE}/inbox/mein-task/materials"
echo "  nano {WORKSPACE}/inbox/mein-task/task.md"
"""

WATCHDOG_SH = f"""#!/bin/bash
TIMEOUT=${{1:-{MAX_TASK_MINUTES * 60 + 120}}}
HEARTBEAT="/tmp/24x7-heartbeat.log"
LOGFILE="/tmp/24x7-$(date +%Y%m%d).log"

echo "🔍 24x7 Watchdog aktiv (Timeout: ${{TIMEOUT}}s)"
echo ""

while true; do
  if [ ! -f "$HEARTBEAT" ]; then
    echo "⏳ $(date +%H:%M:%S): Warte auf Heartbeat..."
    sleep 10
    continue
  fi

  if stat -f %m "$HEARTBEAT" > /dev/null 2>&1; then
    LAST=$(stat -f %m "$HEARTBEAT")
  else
    LAST=$(stat -c %Y "$HEARTBEAT")
  fi

  NOW=$(date +%s)
  DIFF=$((NOW - LAST))

  # Status
  INBOX_COUNT=$(find "{WORKSPACE}/inbox" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  WORKING_COUNT=$(find "{WORKSPACE}/working" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  DONE_COUNT=$(find "{WORKSPACE}/outbox" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  FAILED_COUNT=$(find "{WORKSPACE}/failed" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')

  if [ $DIFF -gt $TIMEOUT ]; then
    echo "⚠️  $(date +%H:%M:%S): KEIN HEARTBEAT seit ${{DIFF}}s!"
    osascript -e 'display notification "Claude 24x7 hängt!" with title "24x7 Watchdog"' 2>/dev/null || true
  else
    echo "✅ $(date +%H:%M:%S): OK (${{DIFF}}s) | 📥$INBOX_COUNT 🔄$WORKING_COUNT ✅$DONE_COUNT ❌$FAILED_COUNT"
  fi

  sleep 60
done
"""

SANDBOX_SB = gemeinsam.sandbox_profil(_NAMEN)

EXAMPLE_TASK = """## Task: README für Projekt erstellen
Priorität: mittel

### Auftrag
Lies die Dateien in materials/ und erstelle eine professionelle README.md.
Struktur: Projekttitel, Beschreibung, Installation, Usage, Lizenz.

### Input
- materials/package.json — Projektinfos und Dependencies

### Erwarteter Output
- output/README.md — Die fertige README

### Hinweis
Alle Arbeit findet NUR im Arbeitsverzeichnis statt. Keine externen Pfade.
"""

README = f"""# Claude 24x7 — Endless Runner

## Quick Start

```bash
# 1. Unzip and install
unzip 24x7-setup.zip
cd {WORKSPACE}
# The * glob does not match dotfiles, .claude needs its own step
cp -r /path/to/24x7-setup/* .
if [ -e .claude/settings.json ]; then
  echo "STOP: .claude/settings.json exists, merge it (see below)"
else
  mkdir -p .claude
  cp -R /path/to/24x7-setup/.claude/. .claude/
fi
test -f .claude/settings.json && echo "hooks in place" || echo "WARNING: no hooks"
chmod +x runner.sh runner-bg.sh watchdog.sh 24x7-docker.sh

# 2. Start, isolated (the default)
cd {WORKSPACE}
export ANTHROPIC_API_KEY=sk-ant-...
./24x7-docker.sh              # builds the container and starts the runner in it
./24x7-docker.sh --logs       # same, and follows the log

# 3. Watchdog (second terminal, host runs only)
./watchdog.sh
```

## Existing .claude/settings.json

Copying would drop your own hooks, permissions, and MCP settings. Merge instead.
The command keeps your entries and appends the 24x7 hooks per event type:

```bash
jq -s '(.[0].hooks // {{}}) as $mine | (.[1].hooks // {{}}) as $new
       | (.[0] * .[1])
       | .hooks = (reduce (($mine | to_entries[]), ($new | to_entries[])) as $e
                   ({{}}; .[$e.key] = ((.[$e.key] // []) + $e.value)))' \\
  .claude/settings.json /path/to/24x7-setup/.claude/settings.json \\
  > .claude/settings.merged.json

# read it, then take it over
mv .claude/settings.merged.json .claude/settings.json
```

## Drop a Task

```bash
# Create task folder
mkdir -p {WORKSPACE}/inbox/my-task/materials

# Copy input files
cp my-files.* {WORKSPACE}/inbox/my-task/materials/

# Write the assignment
cat > {WORKSPACE}/inbox/my-task/task.md << 'EOF'
## Task: My Assignment
Priority: high

### Assignment
[What to do]

### Input
[Which files in materials/ are relevant]

### Expected Output
[What should appear in output/]
EOF

# The runner picks it up automatically!
```

## Collect Results

```bash
ls {WORKSPACE}/outbox/my-task/output/
```

## Check Status

The watchdog shows live counters: inbox | working | done | failed

## Stop

```bash
pkill -f "runner.sh"
# or
kill $(cat /tmp/24x7.pid 2>/dev/null)
```

## Isolation

`runner.sh` refuses to start without isolation. The state is **measured, not
declared**. An environment variable cannot unlock it:

| State | How it is reached | How it is verified | What it means |
|---|---|---|---|
| `docker` | `./24x7-docker.sh` | `/.dockerenv`, `/run/.containerenv`, `/proc/1/cgroup` or an overlay root | Only `{WORKSPACE}` is mounted, as `/workspace`. No home directory, no `~/.claude`, no neighbouring projects. Outbound traffic goes through a proxy that allows {NETZ_ALLOWLIST_TEXT} and answers everything else with 403. The image also brings `timeout`, which the task cap needs and a stock macOS does not have. |
| `seatbelt` | `sandbox-exec -f sandbox.sb ./runner.sh` | the runner can list the workspace but not `/Users`, because the profile denies that read | macOS only, kernel-enforced writes. Reads of the rest of the system and outbound traffic on 443 stay open. Apple has deprecated `sandbox-exec`. |
| `keine` | plain `./runner.sh` | neither probe answered | The runner aborts with exit code 3. Deliberate opt-out: `CLAUDE_24X7_ALLOW_UNSANDBOXED=1`. |

`CLAUDE_24X7_SANDBOXED` is a cross-check, not a switch: if what it claims
differs from what was measured, the runner aborts with exit code 3. Setting it
grants nothing.

Tasks still go into `{WORKSPACE}/inbox/<name>/task.md` on the host. That
directory is the mount, so the runner in the container sees a new task
immediately.

What the container does not give you: the watchdog. `/tmp` inside the
container is a tmpfs of its own, and the heartbeat is written there, so a
watchdog started on the host never sees it. Use `{DOCKER_LOGS}` instead.

```bash
./24x7-docker.sh                                  # Container, the default
sandbox-exec -f sandbox.sb ./runner.sh            # macOS option
CLAUDE_24X7_ALLOW_UNSANDBOXED=1 ./runner-bg.sh    # No isolation, on purpose
```

## The Two Barriers

`.claude/settings.json` installs two `PreToolUse` hooks. They look at
different things, and the second one is the newer of the two:

| Matcher | What it examines | What it does |
|---|---|---|
| `Bash` | the command text | blocks `rm` against dangerous targets, `sudo`, `mkfs`, `dd` to a device, `chmod 777`, `curl \| bash`, `eval` |
| `Write\|Edit\|MultiEdit\|NotebookEdit` | the target path | blocks every write outside `{WORKSPACE}`, plus `.claude/settings.json` inside it |

The path guard normalises before it compares: `~/` becomes your home
directory, `.` and `..` are resolved. `{WORKSPACE}/../elsewhere/x` is therefore
outside and gets blocked, and a relative path is resolved against the working
directory Claude Code sends with the call. Without `jq` neither hook can read
its input, and both then block instead of waving the call through.

The root comes from `CLAUDE_24X7_WORKSPACE` at run time and defaults to `{WORKSPACE}`.

**What the path guard does not cover:**

- **Writes through Bash.** `echo > file`, `tee`, `cp`, `mv`, `>>` are Bash
  calls. They reach the first hook, and that one checks no paths.
- **Reads.** Neither hook looks at `Read`, `Grep` or `cat`. Whatever is
  readable stays readable.
- **Symlinks.** The comparison is textual. A link inside the directory that
  points outside is not followed and passes.
- **Two names for one directory.** To a text comparison `/tmp` and
  `/private/tmp` are two places; on macOS they are one.
- **Tools from MCP servers.** They carry their own names, and no matcher here
  catches them.
- **A `.claude/settings.json` that never got installed.** Both hooks exist
  only if that file is in place: `test -f .claude/settings.json`.

## Without a Container (macOS)

The seatbelt profile is the fallback when Docker is not available. It fences
writes at the kernel level and nothing else.

```bash
sandbox-exec -f sandbox.sb ./runner.sh
```

## Folder Reference

| Folder | Purpose |
|--------|---------|
| inbox/ | Tasks wait here. Oldest is processed first. |
| working/ | Currently being processed. Max 1 task at a time. |
| outbox/ | Completed. Contains output/ with results + log.md |
| failed/ | Failed or timed out. log.md contains error info. |
| idle/ | What Claude does when the queue is empty. |

## Configuration

| Parameter | Value | Change in |
|-----------|-------|-----------|
| Poll interval | {POLL_INTERVAL}s | runner.sh: POLL= |
| Task timeout | {MAX_TASK_MINUTES} min | runner.sh: MAX_SECONDS= |
| Idle timeout | {IDLE_TIMEOUT_MINUTES} min | runner.sh: IDLE_SECONDS= |
| Idle behavior | {IDLE_BEHAVIOR} | idle/idle-tasks.md |

---

Autonomy zones and error tolerance inspired by [AlpiType — Solving the AI Agent Approval Loop](https://alpitype.de/insights/ki-agenten-approval-loop/)

**Disclaimer:** This project was created privately, to the best of the author's knowledge. Use at your own risk. No warranty of completeness, correctness, or fitness for any particular purpose.
"""

# ════════════════════════════════════════════════════════════
#  ZIP BAUEN
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Zielpfad ueberschreibbar, damit der Generator auch ausserhalb der
    # Claude-Umgebung schreiben kann (Tests, CI, lokale Laeufe).
    ZIP_PATH = os.environ.get("CLAUDE_24X7_OUT", "/mnt/user-data/outputs/24x7-setup.zip")
    os.makedirs(os.path.dirname(ZIP_PATH) or ".", exist_ok=True)

    idle_content = IDLE_TASKS.get(IDLE_BEHAVIOR, IDLE_TASKS["sleep"])

    files = {
        "CLAUDE.md": CLAUDE_MD,
        ".claude/settings.json": json.dumps(SETTINGS, indent=2, ensure_ascii=False),
        "runner.sh": RUNNER_SH,
        "runner-bg.sh": RUNNER_BG_SH,
        "watchdog.sh": WATCHDOG_SH,
        "24x7-docker.sh": DOCKER_SH,
        "Dockerfile": DOCKERFILE,
        "docker-compose.yml": DOCKER_COMPOSE,
        "sandbox.sb": SANDBOX_SB,
        "idle/idle-tasks.md": idle_content,
        "inbox/.gitkeep": "",
        "working/.gitkeep": "",
        "outbox/.gitkeep": "",
        "failed/.gitkeep": "",
        "inbox/beispiel-task/task.md": EXAMPLE_TASK,
        "inbox/beispiel-task/materials/.gitkeep": "",
        "README.md": README,
    }

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(f"24x7-setup/{filename}", content)

    print(f"✅ 24x7-setup.zip erstellt: {ZIP_PATH}")
    print(f"   Workspace:      {WORKSPACE}")
    print(f"   Poll-Intervall:  {POLL_INTERVAL}s")
    print(f"   Task-Timeout:    {MAX_TASK_MINUTES} Min")
    print(f"   Idle-Verhalten:  {IDLE_BEHAVIOR}")
    print(f"   Dateien:         {len(files)}")
