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

# Budget fuer den ganzen Daemon-Lauf, nicht pro Task. Zur Laufzeit ueber
# CLAUDE_24X7_BUDGET_USD ueberschreibbar. Wer die Grenze erreicht, bekommt
# keinen weiteren Aufruf: der Daemon endet mit 9. Ein Neustart faengt neu
# an zu zaehlen, auch der des Watchdogs.
BUDGET_USD = os.environ.get("CLAUDE_24X7_BUDGET_USD", "50.00")
# Zusaetzliche Obergrenze in Tokens (Ein- plus Ausgabe). 0 heisst: keine.
BUDGET_TOKENS = os.environ.get("CLAUDE_24X7_BUDGET_TOKENS", "0")

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
COST_SH = gemeinsam.cost_sh("24x7")
RECEIPT_SH = gemeinsam.receipt_sh("24x7", "runner.sh")

RUNNER_SH = f"""#!/bin/bash
set -uo pipefail

WORKSPACE="${{CLAUDE_24X7_WORKSPACE:-{WORKSPACE}}}"
INBOX="$WORKSPACE/inbox"
WORKING="$WORKSPACE/working"
OUTBOX="$WORKSPACE/outbox"
FAILED="$WORKSPACE/failed"
IDLE="$WORKSPACE/idle"
POLL={POLL_INTERVAL}
# Fristen zur Laufzeit ueberschreibbar, wie das Budget. Wer sie aendern will,
# soll dafuer nicht das Setup neu erzeugen muessen.
MAX_SECONDS="${{CLAUDE_24X7_MAX_SECONDS:-{MAX_TASK_MINUTES * 60}}}"
IDLE_SECONDS="${{CLAUDE_24X7_IDLE_SECONDS:-{IDLE_TIMEOUT_MINUTES * 60}}}"
LOGFILE="/tmp/24x7-$(date +%Y%m%d).log"

# Budget fuer den ganzen Lauf, nicht pro Task. Der Zaehler sieht immer nur
# einen Strom, deshalb bekommt er vor jedem Aufruf den Rest und nicht die
# Gesamtsumme. So erzwingt derselbe Zaehler, den Nightshift benutzt, eine
# Grenze ueber viele Aufrufe hinweg, ohne dass die Rechnung zweimal existiert.
BUDGET_USD="${{CLAUDE_24X7_BUDGET_USD:-{BUDGET_USD}}}"
BUDGET_TOKENS="${{CLAUDE_24X7_BUDGET_TOKENS:-{BUDGET_TOKENS}}}"
SUMMENDATEI="$WORKSPACE/24x7-kosten.json"
SUMME_USD=0
SUMME_EIN=0
SUMME_AUS=0
SUMME_VOLLSTAENDIG=1
CLAUDE_PIDDATEI="/tmp/24x7-claude-$$.pid"
RCDATEI="/tmp/24x7-rc-$$"
STOPMARKER="/tmp/24x7-budget-stop-$$"
BUDGET_STOP=0
# Jeder Claude-Aufruf, auch der im Leerlauf. TASK_COUNT zaehlt nur Tasks, und
# gerade der Leerlauf ist es, der auf einem leeren Posteingang das Geld kostet.
AUFRUF_COUNT=0

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
# Denselben Ort wie der Watchdog, der CLAUDE_24X7_PIDDATEI liest. Ein fest
# verdrahteter Pfad hier laesst ihn bei gesetzter Variable ins Leere sehen.
PIDFILE="${{CLAUDE_24X7_PIDDATEI:-/tmp/24x7.pid}}"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "❌ 24x7 Runner läuft bereits (PID $(cat "$PIDFILE"))"
    echo "   Beenden: kill $(cat "$PIDFILE")"
    exit 1
fi
echo $$ > "$PIDFILE"

# ── Kosten: messen, summieren, stoppen ──────────────────────
# awk statt jq: der Zaehler faellt ohne jq auf "unbekannt" zurueck und laesst
# den Lauf weiterlaufen, und dieselbe Nachsicht gilt hier. Fehlt die Zahl,
# bleibt die Summe stehen und wird als unvollstaendig gekennzeichnet, statt
# eine Null zu behaupten, die niemand gemessen hat.
zahl_aus_json() {{
    [ -f "$1" ] || return 1
    # grep und sed statt awk mit Anfuehrungszeichen im Muster: der Generator
    # baut diesen Text als f-String, und jede Backslash-Folge haette hier
    # zwei Ebenen zu ueberleben. Zwei Werkzeuge ohne Escapes sind leichter
    # richtig zu halten als ein awk-Programm, das zweimal maskiert ist.
    ZEILE=$(grep -m1 -- "$2" "$1" 2>/dev/null) || return 1
    WERT=$(printf '%s' "$ZEILE" | sed -e 's/.*: *//' -e 's/[",]//g' -e 's/[[:space:]]//g')
    case "$WERT" in
        ''|*[!0-9.-]*) return 1 ;;
    esac
    printf '%s' "$WERT"
}}

summe_schreiben() {{
    # Die Datei entsteht als Here-Doc, nicht in awk. awk braeuchte hier
    # Anfuehrungszeichen und Zeilenumbrueche als Escape-Folgen, und die
    # muessten den f-String des Generators und die Shell heil ueberstehen.
    USD_TXT=$(LC_ALL=C awk -v u="$SUMME_USD" 'BEGIN {{ printf("%.4f", u + 0) }}')
    VOLL=false
    [ "$SUMME_VOLLSTAENDIG" -eq 1 ] && VOLL=true
    UEBER=false
    [ "$BUDGET_STOP" -eq 1 ] && UEBER=true
    cat > "$SUMMENDATEI" 2>/dev/null <<ENDE || true
{{
  "usd_geschaetzt": $USD_TXT,
  "tokens_ein": $SUMME_EIN,
  "tokens_aus": $SUMME_AUS,
  "summe_vollstaendig": $VOLL,
  "budget_usd": $BUDGET_USD,
  "budget_ueberschritten": $UEBER,
  "aufrufe": ${{AUFRUF_COUNT:-0}},
  "tasks": ${{TASK_COUNT:-0}},
  "preise_stand": "{gemeinsam.PREISE_STAND}"
}}
ENDE
}}

summe_addieren() {{
    KOSTEN="$1"
    U=$(zahl_aus_json "$KOSTEN" usd_geschaetzt) || U=""
    if [ -z "$U" ]; then
        SUMME_VOLLSTAENDIG=0
    else
        SUMME_USD=$(LC_ALL=C awk -v a="$SUMME_USD" -v b="$U" 'BEGIN {{ printf("%.6f", a + b) }}')
        E=$(zahl_aus_json "$KOSTEN" tokens_ein) || E=0
        A=$(zahl_aus_json "$KOSTEN" tokens_aus) || A=0
        SUMME_EIN=$((SUMME_EIN + E))
        SUMME_AUS=$((SUMME_AUS + A))
    fi
    summe_schreiben
}}

# Was vom Budget noch uebrig ist. Der Zaehler bekommt diesen Rest, nicht das
# ganze Budget: sonst duerfte jeder einzelne Aufruf die volle Summe kosten.
rest_usd() {{
    LC_ALL=C awk -v b="$BUDGET_USD" -v s="$SUMME_USD" 'BEGIN {{
        if (b + 0 <= 0) {{ print 0; exit }}
        r = b - s
        printf("%.4f", (r > 0 ? r : 0.0001))
    }}'
}}

rest_tokens() {{
    LC_ALL=C awk -v b="$BUDGET_TOKENS" -v e="$SUMME_EIN" -v a="$SUMME_AUS" 'BEGIN {{
        if (b + 0 <= 0) {{ print 0; exit }}
        r = b - e - a
        printf("%d", (r > 0 ? r : 1))
    }}'
}}

# Ein Claude-Aufruf, mitgezaehlt.
#   $1 Datei fuer die Kostenschaetzung dieses Aufrufs
#   $2 Frist in Sekunden
#   $3 Prompt
# Setzt RC auf den Rueckgabewert von claude beziehungsweise timeout.
#
# Der Aufbau stammt aus dem Nightshift-Runner und ist kein Selbstzweck: der
# Rueckgabewert reist ueber eine Datei, weil das Ende der Pipeline dem Zaehler
# gehoert und "$?" dessen Wert waere. "set -m" gibt dem timeout-Prozess eine
# eigene Prozessgruppe, deren ID seine PID ist; nur so trifft der Budget-Stop
# auch Enkel, egal wie timeout Signale weiterreicht.
claude_mit_zaehler() {{
    KOSTENDATEI="$1"
    FRIST="$2"
    PROMPT="$3"
    AUFRUF_COUNT=$((AUFRUF_COUNT + 1))
    rm -f "$RCDATEI" "$STOPMARKER" "$CLAUDE_PIDDATEI"
    set -m
    {{
        set -m
        "$TIMEOUT_BIN" "$FRIST" claude -p "$PROMPT" \
          --dangerously-skip-permissions \
          --output-format stream-json \
          --verbose \
          </dev/null 2>&1 &
        X7_CLAUDE=$!
        echo "$X7_CLAUDE" > "$CLAUDE_PIDDATEI"
        set +m
        wait "$X7_CLAUDE"
        echo $? > "$RCDATEI"
    }} | tee -a "$LOGFILE" \
      | bash "$WORKSPACE/24x7-cost.sh" \
            "$KOSTENDATEI" "$(rest_usd)" "$(rest_tokens)" \
            "$CLAUDE_PIDDATEI" "$STOPMARKER" &
    wait $! 2>/dev/null
    set +m
    RC=$(cat "$RCDATEI" 2>/dev/null || echo 1)
    case "${{RC:-}}" in ''|*[!0-9]*) RC=1 ;; esac
    rm -f "$CLAUDE_PIDDATEI" "$RCDATEI"
    summe_addieren "$KOSTENDATEI"
    if [ -f "$STOPMARKER" ]; then
        BUDGET_STOP=1
        summe_schreiben
    fi
}}

# Graceful Shutdown
cleanup() {{
    # RC vor allem anderen: "$?" waere nach dem ersten Kommando im Rumpf
    # dessen Wert und nicht mehr der, mit dem der Runner endet. Der alte
    # Rumpf endete fest mit "exit 0" und machte damit aus einem Budget-Stop
    # oder einem Isolationsabbruch ein sauberes Ende.
    RC=${{1:-$?}}
    trap - EXIT
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
    rm -f "$PIDFILE" "$CLAUDE_PIDDATEI" "$RCDATEI" "$STOPMARKER"
    summe_schreiben
    exit "$RC"
}}
trap 'cleanup 143' SIGTERM
trap 'cleanup 130' SIGINT
trap cleanup EXIT

# Ordner anlegen
mkdir -p "$INBOX" "$WORKING" "$OUTBOX" "$FAILED" "$IDLE"

echo "============================================" | tee -a "$LOGFILE"
echo "  Claude 24x7 Runner gestartet: $(date)" | tee -a "$LOGFILE"
echo "  Workspace: $WORKSPACE" | tee -a "$LOGFILE"
echo "  Poll-Intervall: ${{POLL}}s" | tee -a "$LOGFILE"
echo "  Task-Timeout: ${{MAX_SECONDS}}s, Leerlauf ${{IDLE_SECONDS}}s (via $TIMEOUT_BIN)" | tee -a "$LOGFILE"
echo "  Idle: {IDLE_BEHAVIOR}" | tee -a "$LOGFILE"
echo "  Isolation: $ISOLATION" | tee -a "$LOGFILE"
echo "  Log: $LOGFILE" | tee -a "$LOGFILE"
echo "  PID: $$" | tee -a "$LOGFILE"
echo "============================================" | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"
echo "⚠️  KOSTEN: 24x7 erzeugt kontinuierlich API-Calls." | tee -a "$LOGFILE"
echo "   Budget fuer diesen Lauf: $BUDGET_USD USD. Danach endet der Runner mit 9." | tee -a "$LOGFILE"
echo "   Laufende Summe: $SUMMENDATEI" | tee -a "$LOGFILE"
echo "   Die Schaetzung ist eine Schaetzung. Das Anthropic-Dashboard bleibt massgeblich." | tee -a "$LOGFILE"
echo "   Der Leerlauf ruft Claude auf und zaehlt mit. IDLE_BEHAVIOR=sleep schaltet ihn ab." | tee -a "$LOGFILE"
echo "" | tee -a "$LOGFILE"

# Heartbeat zurücksetzen
> /tmp/24x7-heartbeat.log

TASK_COUNT=0
summe_schreiben

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
    TASK_START="$(date -Iseconds 2>/dev/null || date)"
    echo "   ▶ Claude startet..." | tee -a "$LOGFILE"
    claude_mit_zaehler "$WORKING/$TASK_NAME/cost.json" "$MAX_SECONDS" \\
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
- Wenn fertig: Session beenden"

    EXIT_CODE=$RC

    if [ "$BUDGET_STOP" -eq 1 ]; then
      # Budget zuerst, sonst wuerde ein durch den Stop beendeter Claude als
      # gewoehnlicher Fehler in failed/ landen und niemand saehe den Grund.
      echo "BUDGET-STOP: Der Lauf wurde bei $BUDGET_USD USD beendet." >> "$WORKING/$TASK_NAME/log.md" 2>/dev/null
      mv "$WORKING/$TASK_NAME" "$FAILED/$TASK_NAME"
      echo "   💸 Budget erreicht → failed/$TASK_NAME" | tee -a "$LOGFILE"
      echo "   Schaetzung: $SUMME_USD USD von $BUDGET_USD. Details in $SUMMENDATEI." | tee -a "$LOGFILE"
      cleanup 9
    elif [ $EXIT_CODE -eq 0 ]; then
      # Erfolg → outbox
      mv "$WORKING/$TASK_NAME" "$OUTBOX/$TASK_NAME"
      echo "   ✅ Erledigt → outbox/$TASK_NAME ($(date +%H:%M:%S))" | tee -a "$LOGFILE"
    elif [ $EXIT_CODE -eq 124 ]; then
      # Timeout
      echo "TIMEOUT" > "$WORKING/$TASK_NAME/log.md"
      mv "$WORKING/$TASK_NAME" "$FAILED/$TASK_NAME"
      echo "   ⏰ Timeout nach ${{MAX_SECONDS}}s → failed/$TASK_NAME" | tee -a "$LOGFILE"
    else
      # Fehler
      echo "EXIT CODE: $EXIT_CODE" >> "$WORKING/$TASK_NAME/log.md" 2>/dev/null
      mv "$WORKING/$TASK_NAME" "$FAILED/$TASK_NAME"
      echo "   ❌ Fehler (Exit $EXIT_CODE) → failed/$TASK_NAME" | tee -a "$LOGFILE"
    fi

    # Receipt fuer diesen Task. Der Ordner ist inzwischen verschoben, also
    # wird er dort gesucht, wo er gelandet ist.
    for ORT in "$OUTBOX/$TASK_NAME" "$FAILED/$TASK_NAME"; do
      [ -d "$ORT" ] || continue
      NS_RUNID="$TASK_NAME" NS_START="$TASK_START" NS_EXIT="$EXIT_CODE" \\
      NS_ISOLATION="$ISOLATION" NS_KOSTEN="$ORT/cost.json" NS_ZIEL="$ORT" \\
      NS_GENRE="task" NS_AUFGABE="$TASK_NAME" \\
      NS_RUNBOOK="$ORT/task.md" NS_STALL="/tmp/24x7-stall" \\
        bash "$WORKSPACE/24x7-receipt.sh" >/dev/null 2>&1 || true
      break
    done

    echo "" | tee -a "$LOGFILE"

  else
    # Keine Tasks → Idle
    echo "💤 Keine Tasks. Idle-Modus... ($(date +%H:%M:%S))" | tee -a "$LOGFILE"

    IDLE_DIR="$WORKING/idle-$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$IDLE_DIR/output"
    cp "$IDLE/idle-tasks.md" "$IDLE_DIR/task.md" 2>/dev/null

    if [ -f "$IDLE_DIR/task.md" ] && ! grep -q "Session sofort beenden" "$IDLE_DIR/task.md"; then
      # Der Leerlauf ruft Claude auf und kostet damit Geld. Bei
      # IDLE_BEHAVIOR=cleanup arbeitet er bis zu {IDLE_TIMEOUT_MINUTES}
      # Minuten und pausiert danach nur {POLL_INTERVAL} Sekunden; ein leerer
      # Posteingang kostet also fast so viel wie ein voller. Deshalb zaehlt
      # er gegen dasselbe Budget wie ein Task. Wer das nicht will, generiert
      # das Setup mit IDLE_BEHAVIOR=sleep.
      claude_mit_zaehler "$IDLE_DIR/cost.json" "$IDLE_SECONDS" \\
        "Du bist im Idle-Modus. Lies $IDLE_DIR/task.md und arbeite die Idle-Aufgaben ab.
Ergebnisse in $IDLE_DIR/output/ ablegen.
Workspace-Root ist $WORKSPACE.
Wenn fertig: Session beenden."

      if [ "$BUDGET_STOP" -eq 1 ]; then
        rm -rf "$IDLE_DIR"
        echo "   💸 Budget im Leerlauf erreicht: $SUMME_USD USD von $BUDGET_USD." | tee -a "$LOGFILE"
        echo "   Details in $SUMMENDATEI." | tee -a "$LOGFILE"
        cleanup 9
      fi

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

_WATCHDOG = dict(
    _NAMEN,
    MARKE="24x7",
    AKTIONVAR="CLAUDE_24X7_WATCHDOG_AKTION",
    NEUSTARTVAR="CLAUDE_24X7_WATCHDOG_NEUSTARTS",
    FRISTVAR="CLAUDE_24X7_WATCHDOG_FRIST",
    PIDVAR="CLAUDE_24X7_PIDDATEI",
    PIDDATEI="/tmp/24x7.pid",
    STARTSKRIPT="runner-bg.sh",
)

WATCHDOG_SH = f"""#!/bin/bash
TIMEOUT=${{1:-{MAX_TASK_MINUTES * 60 + 120}}}
HEARTBEAT="${{CLAUDE_24X7_HEARTBEAT:-/tmp/24x7-heartbeat.log}}"
WORKSPACE="${{CLAUDE_24X7_WORKSPACE:-{WORKSPACE}}}"
@@REAKTION@@
echo "🔍 24x7 Watchdog aktiv (Timeout: ${{TIMEOUT}}s, Aktion: $AKTION)"
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
  INBOX_COUNT=$(find "$WORKSPACE/inbox" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  WORKING_COUNT=$(find "$WORKSPACE/working" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  DONE_COUNT=$(find "$WORKSPACE/outbox" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')
  FAILED_COUNT=$(find "$WORKSPACE/failed" -mindepth 1 -maxdepth 1 -type d 2>/dev/null | wc -l | tr -d ' ')

  if [ $DIFF -gt $TIMEOUT ]; then
    echo "⚠️  $(date +%H:%M:%S): KEIN HEARTBEAT seit ${{DIFF}}s!"
    osascript -e 'display notification "Claude 24x7 haengt!" with title "24x7 Watchdog"' 2>/dev/null || true
    stillstand_behandeln
  else
    echo "✅ $(date +%H:%M:%S): OK (${{DIFF}}s) | 📥$INBOX_COUNT 🔄$WORKING_COUNT ✅$DONE_COUNT ❌$FAILED_COUNT"
  fi

  sleep 60
done
""".replace(
    "@@REAKTION@@", gemeinsam.watchdog_reaktion(_WATCHDOG)
)

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

## Watchdog

```bash
./watchdog.sh                       # Alert after the task timeout plus two minutes without heartbeat
./watchdog.sh 300                   # Alert after 5 min
```

Detecting a stall was always there. Reacting to one is what the three actions
add. Set `CLAUDE_24X7_WATCHDOG_AKTION`:

| Action | What happens on a stall |
|---|---|
| `melden` (default) | One line on stdout and a macOS notification. Nothing is stopped. |
| `beenden` | `TERM` to the PID in `/tmp/24x7.pid`, `KILL` after `CLAUDE_24X7_WATCHDOG_FRIST` seconds (default 20), then the watchdog exits. |
| `neustart` | The same, and then the run is started again, at most `CLAUDE_24X7_WATCHDOG_NEUSTARTS` times (default 1). |

```bash
CLAUDE_24X7_WATCHDOG_AKTION=neustart ./watchdog.sh 600
```

**A run that ended on its own is never restarted.** The watchdog only restarts
what it just terminated itself, and it recognises that by a live PID in
`/tmp/24x7.pid`. A budget stop ends the run, so afterwards there is no live PID
and the watchdog reports instead of restarting. Same for a crash and for a
finished run. A restart begins with an empty `working/`: the runner moves the task it was on to `failed/` while shutting down, and picks the next one from `inbox/`.

**What the watchdog does not cover:**

- **A busy loop.** The heartbeat comes from the `PostToolUse` hook. Claude
  retrying the same failing test forever keeps writing heartbeats, and to the
  watchdog that looks healthy. The task timeout is the backstop there, not the watchdog.
- **A run in the container.** `/tmp` inside the container is a tmpfs of its
  own, so the heartbeat never reaches the host and a watchdog started there
  waits forever. Read `docker compose logs -f 24x7` instead.
- **The reason for the stall.** It restarts, it does not diagnose. If the run
  hangs on the same step every time, the restart budget runs out and the
  watchdog exits.
- **Being started at all.** It is a separate script in a second terminal, and
  nothing starts it for you.
- **The isolation the original run had.** The restart runs `runner-bg.sh`, a
  bare `nohup bash runner.sh`, and the new run inherits the watchdog's
  environment rather than the terminated run's. A runner fenced by
  `sandbox-exec` comes back unfenced, measures `keine` and refuses with exit
  code 3. That fails closed, but it means `neustart` completes only for a
  host run whose watchdog shell carries the same
  `CLAUDE_24X7_ALLOW_UNSANDBOXED=1`.

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
- **Symlinks are followed, but the check is not atomic.** Both the root and the
  target are resolved physically before they are compared, so a link inside the
  directory pointing outside is blocked. A link created between the check and
  the write is not: the hook looked before it existed.
- **Two names for one directory.** `/tmp` and `/private/tmp` are one directory
  on macOS, and the hook now treats them as one, because it compares resolved
  paths.
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
        "24x7-cost.sh": COST_SH,
        "24x7-receipt.sh": RECEIPT_SH,
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
