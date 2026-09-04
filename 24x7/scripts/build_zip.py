#!/usr/bin/env python3
"""
Claude 24x7 — ZIP Builder
Erzeugt einen endlosen Runner mit Inbox/Outbox-Architektur
"""

import json, os, re, zipfile
from datetime import datetime

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

SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "bash -c '"
                            'CMD=$(cat | jq -r ".tool_input.command // empty"); '
                            'if [ -n "$CMD" ] && echo "$CMD" | '
                            "grep -qE \"rm -rf /|rm -rf ~|rm -rf \\\\\\\\*|mkfs|dd if=.* of=/dev/|sudo |chmod 777|curl.*\\\\|.*bash|eval |> /dev/sd\"; "
                            'then echo "24x7 BLOCKED: Destruktiver Befehl" >&2; exit 2; fi; '
                            "exit 0'"
                        ),
                    }
                ],
            }
        ],
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

RUNNER_SH = f"""#!/bin/bash
set -uo pipefail

WORKSPACE="{WORKSPACE}"
INBOX="$WORKSPACE/inbox"
WORKING="$WORKSPACE/working"
OUTBOX="$WORKSPACE/outbox"
FAILED="$WORKSPACE/failed"
IDLE="$WORKSPACE/idle"
POLL={POLL_INTERVAL}
MAX_SECONDS={MAX_TASK_MINUTES * 60}
IDLE_SECONDS={IDLE_TIMEOUT_MINUTES * 60}
LOGFILE="/tmp/24x7-$(date +%Y%m%d).log"

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
echo "  Task-Timeout: {MAX_TASK_MINUTES} Min" | tee -a "$LOGFILE"
echo "  Idle: {IDLE_BEHAVIOR}" | tee -a "$LOGFILE"
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
    timeout $MAX_SECONDS claude -p \\
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
      timeout $IDLE_SECONDS claude -p \\
        "Du bist im Idle-Modus. Lies $IDLE_DIR/task.md und arbeite die Idle-Aufgaben ab.
Ergebnisse in $IDLE_DIR/output/ ablegen.
Workspace-Root ist $WORKSPACE.
Wenn fertig: Session beenden." \\
        --dangerously-skip-permissions \\
        --output-format stream-json \\
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
"""

RUNNER_BG_SH = f"""#!/bin/bash
echo "Starte Claude 24x7 im Hintergrund..."
nohup bash "{WORKSPACE}/runner.sh" > /tmp/24x7-nohup.log 2>&1 &
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

SANDBOX_SB = f"""(version 1)
(deny default)

(allow process-fork process-exec)
(allow signal (target self))

(allow file-read* (subpath "/usr"))
(allow file-read* (subpath "/bin"))
(allow file-read* (subpath "/Library"))
(allow file-read* (subpath "/opt/homebrew"))
(allow file-read* (subpath "/private/tmp"))
(allow file-read* (subpath "/private/var"))
(allow file-read* (subpath "/dev"))
(allow file-read* (subpath "/etc"))
(allow file-read* (subpath "/var"))

;; NUR Workspace + /tmp beschreibbar
(allow file-read* file-write* (subpath "{WORKSPACE}"))
(allow file-read* file-write* (subpath "/tmp"))
(allow file-read* file-write* (subpath "/private/tmp"))

;; Home: nur was Claude Code braucht (read-only)
(allow file-read* (subpath "{HOMEDIR}/.claude"))
(allow file-read* (subpath "{HOMEDIR}/.npm-global"))
(allow file-read* (subpath "{HOMEDIR}/.config"))
(allow file-read* (subpath "{HOMEDIR}/.bun"))
(allow file-read* (subpath "{HOMEDIR}/.nvm"))
(allow file-read* (subpath "{HOMEDIR}/.cargo"))

;; Netzwerk: nur HTTPS
(allow network-outbound (remote tcp "*:443"))
(allow system-socket)
(allow sysctl-read)
(allow mach-lookup)
"""

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
cp -r 24x7-setup/* {WORKSPACE}/
chmod +x {WORKSPACE}/runner.sh {WORKSPACE}/runner-bg.sh {WORKSPACE}/watchdog.sh

# 2. Start
cd {WORKSPACE}
./runner-bg.sh

# 3. Watchdog (second terminal)
./watchdog.sh
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

## With Sandbox (recommended)

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
    ZIP_PATH = "/mnt/user-data/outputs/24x7-setup.zip"

    idle_content = IDLE_TASKS.get(IDLE_BEHAVIOR, IDLE_TASKS["sleep"])

    files = {
        "CLAUDE.md": CLAUDE_MD,
        ".claude/settings.json": json.dumps(SETTINGS, indent=2, ensure_ascii=False),
        "runner.sh": RUNNER_SH,
        "runner-bg.sh": RUNNER_BG_SH,
        "watchdog.sh": WATCHDOG_SH,
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
