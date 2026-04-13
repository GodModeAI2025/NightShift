#!/usr/bin/env python3
"""
Claude Nightshift — ZIP Builder
Erzeugt alle Dateien und packt sie als nightshift-setup.zip
"""

import json, os, re, sys, zipfile
from datetime import datetime

# ╔══════════════════════════════════════════════════════════╗
# ║  DIESE VARIABLEN VOR AUSFÜHRUNG ANPASSEN!               ║
# ╚══════════════════════════════════════════════════════════╝

PROJEKTPFAD = os.environ.get("NIGHTSHIFT_PROJECT", "REPLACE_ME")
if PROJEKTPFAD == "REPLACE_ME":
    raise SystemExit("ERROR: Set PROJEKTPFAD before running, or export NIGHTSHIFT_PROJECT=/your/project")
HOMEDIR = os.path.expanduser("~")
AUFGABE_TITEL = "Auth-Modul auf JWT umstellen"
AUFGABE_KURZ = "nightshift: Auth auf JWT"
TESTBEFEHL = "bun test"
STACK_INFO = "Node.js, TypeScript, Bun"
GENRE = "refactoring"  # refactoring|feature|migration|bugfix|testing|cleanup|devops|documentation
DATUM = datetime.now().strftime("%Y-%m-%d %H:%M")

# ╔══════════════════════════════════════════════════════════╗
# ║  RUNBOOK — VOM SKILL GENERIEREN UND VALIDIEREN!         ║
# ║  Genre-Template als Basis, dann projektspezifisch       ║
# ║  befüllen. Jeder Schritt braucht Dateipfad oder Befehl! ║
# ╚══════════════════════════════════════════════════════════╝

RUNBOOK = f"""## Runbook: {AUFGABE_TITEL}
Genre: {GENRE}
Erstellt: {DATUM}
Projekt: {PROJEKTPFAD}
Stack: {STACK_INFO}
Testbefehl: {TESTBEFEHL}

### Autonomiebereiche
🟢 Frei (ohne Rueckfrage):
- Dateien lesen in src/, tests/, docs/
- Dateien erstellen/aendern in src/, tests/
- Dependencies installieren
- Tests ausfuehren
- Git add + commit

🟡 Protokollpflichtig (in log.md dokumentieren):
- Dateien loeschen
- Konfigurationsdateien aendern
- Mehr als 3 Dateien in einem Schritt aendern

🔴 Verboten:
- Dateien ausserhalb {PROJEKTPFAD}
- Secrets/Credentials anfassen
- Force-Push

### Fehler-Toleranz
- 1 fehlschlagender Test: Fix versuchen, max. 2 Versuche, dann weiter
- 2-3 fehlschlagende Tests: Warnung in log.md, Phase abschliessen
- Ueber 3 fehlschlagende Tests: STOPPEN, `git stash`, log.md schreiben
- Linter-Warnings: Ignorieren, nur Errors zaehlen

### Vorbedingungen
- [ ] Git-Status: clean working tree
- [ ] Bestehende Tests gruen: `{TESTBEFEHL}`

### Phase 1: Vorbereitung
- [ ] Schritt mit konkretem Dateipfad oder Befehl

### Phase 2: Implementierung
- [ ] Schritt mit konkretem Dateipfad oder Befehl

### Phase 3: Verifikation
- [ ] `{TESTBEFEHL}` ausfuehren — alle Tests gruen
- [ ] Geaenderte Dateien reviewen

### Abschluss
- [ ] Getroffene Entscheidungen in decisions.md dokumentieren (erstellen falls nicht vorhanden)
- [ ] CHANGELOG.md aktualisieren
- [ ] `git add -A && git commit -m '{AUFGABE_KURZ}'`

### Rollback
Falls etwas schiefgeht:
```
git checkout .
```
"""


# ════════════════════════════════════════════════════════════
#  RUNBOOK VALIDIERUNG
# ════════════════════════════════════════════════════════════

VAGUE_PATTERNS = [
    r"^- \[ \] (?:Code schreiben|Implementieren|Refactoring durchf|Alles testen|Auth implementieren|Feature bauen|Bug fixen)$",
    r"^- \[ \] (?:Weitermachen|Fertig machen|Rest erledigen|Aufräumen)$",
]

def validate_runbook(runbook_text):
    """Validiert das Runbook und gibt (passed, total, details) zurück."""
    checks = []

    # Struktur-Checks
    checks.append(("Hat Vorbedingungen-Phase",
                    "### Vorbedingungen" in runbook_text or "### Vorbedingung" in runbook_text))
    checks.append(("Hat Verifikations-Phase",
                    "### Phase" in runbook_text and ("Verifikation" in runbook_text or "Test" in runbook_text)))
    checks.append(("Hat Abschluss mit git commit",
                    "git commit" in runbook_text or "git add" in runbook_text))
    checks.append(("Hat Rollback-Anweisung",
                    "### Rollback" in runbook_text or "git checkout" in runbook_text))

    # Schritte zählen
    steps = re.findall(r"^- \[ \]", runbook_text, re.MULTILINE)
    step_count = len(steps)
    checks.append((f"Maximal 20 Schritte (aktuell: {step_count})", step_count <= 20))
    checks.append((f"Mindestens 5 Schritte (aktuell: {step_count})", step_count >= 5))

    # Qualität: Jeder Schritt prüfen
    step_lines = re.findall(r"^- \[ \] .+$", runbook_text, re.MULTILINE)
    vague_steps = []
    empty_steps = []
    for line in step_lines:
        content = line.replace("- [ ] ", "").strip()
        # Prüfe auf Dateipfade, Befehle, oder konkrete Aktionen
        has_path = bool(re.search(r"[/\\]\w+\.\w+|src/|lib/|test/|app/", content))
        has_command = bool(re.search(r"`[^`]+`|npm |bun |pip |cargo |go |git |pytest|make", content))
        has_concrete = bool(re.search(r"erstellen|anlegen|ändern|umbauen|hinzufügen|entfernen|ersetzen|schreiben|einfügen|aktualisieren|konfigurieren|installieren|ausfuehren|ausführen|prüfen|Funktion|Klasse|Interface|Modul|Datei|Route|Endpoint|Tabelle|Schema|Migration", content, re.IGNORECASE))
        if not (has_path or has_command or has_concrete):
            if len(content) < 30:
                vague_steps.append(content)

        for pattern in VAGUE_PATTERNS:
            if re.match(pattern, line):
                vague_steps.append(content)

    checks.append((f"Keine vagen Formulierungen ({len(vague_steps)} gefunden)",
                    len(vague_steps) == 0))
    checks.append(("Testbefehl ist konkret",
                    bool(re.search(r"`[^`]+`", runbook_text)) and "Testbefehl" in runbook_text))

    # Sicherheit
    checks.append(("Kein rm -rf in Schritten",
                    "rm -rf" not in runbook_text.split("### Rollback")[0] if "### Rollback" in runbook_text else "rm -rf" not in runbook_text))
    checks.append(("Keine Secrets/Credentials hardcoded",
                    not bool(re.search(r"(password|secret|token|api.key)\s*[:=]\s*['\"][^'\"]{8,}", runbook_text, re.IGNORECASE))))
    checks.append(("Keine Aktionen ausserhalb Projektordner",
                    not bool(re.search(r"(/usr/|/etc/|/var/|~/\.|/home/(?!claude))", runbook_text))))

    # Genre-Check
    checks.append((f"Genre '{GENRE}' angegeben",
                    f"Genre: {GENRE}" in runbook_text or f"Genre: " in runbook_text))

    # Autonomie-Check
    has_green = bool(re.search(r"🟢|Frei \(", runbook_text))
    has_yellow = bool(re.search(r"🟡|Protokollpflichtig", runbook_text))
    has_red = bool(re.search(r"🔴|Verboten", runbook_text))
    checks.append(("Hat Autonomiebereiche (3 Zonen)",
                    has_green and has_yellow and has_red))

    # Fehler-Budget-Check
    checks.append(("Hat Fehler-Toleranz definiert",
                    "Fehler-Toleranz" in runbook_text or "Fehler-Budget" in runbook_text))

    # Fehler-Budget nicht zu permissiv
    has_stop_condition = bool(re.search(r"STOPPEN|stoppen|pausieren|abbrechen", runbook_text))
    checks.append(("Fehler-Budget hat Stop-Bedingung",
                    has_stop_condition))

    passed = sum(1 for _, ok in checks if ok)
    total = len(checks)

    return passed, total, checks, vague_steps


def print_validation(passed, total, checks, vague_steps):
    """Gibt die Validierungsergebnisse aus."""
    print("╔══════════════════════════════════════════════════════════╗")
    print("║  RUNBOOK VALIDIERUNG                                     ║")
    print("╠══════════════════════════════════════════════════════════╣")

    for label, ok in checks:
        icon = "✅" if ok else "❌"
        print(f"║  {icon} {label:<52} ║")

    print("╠══════════════════════════════════════════════════════════╣")
    status = "BESTANDEN" if passed == total else "FEHLER"
    print(f"║  Ergebnis: {passed}/{total} bestanden — {status:<27} ║")
    print("╚══════════════════════════════════════════════════════════╝")

    if vague_steps:
        print("\n⚠️  Vage Schritte gefunden:")
        for s in vague_steps:
            print(f"   → \"{s}\"")
        print("   Tipp: Dateipfad, Befehl oder konkrete Aktion ergänzen")


# ════════════════════════════════════════════════════════════
#  GENRE TEMPLATES (Referenz — vom Skill genutzt zum Befüllen)
# ════════════════════════════════════════════════════════════

GENRE_TEMPLATES = {
    "refactoring": {
        "phasen": ["Ist-Analyse", "Testabdeckung sichern", "Umbau", "Verifikation", "Cleanup"],
        "risiko_checks": ["Bestehende Tests VOR Umbau grün?", "Öffentliche API betroffen?", "Breaking Changes?"],
        "pflicht_schritte": ["Bestehende Tests laufen lassen", "Nach jedem Umbauschritt testen"],
    },
    "feature": {
        "phasen": ["Vorbereitung", "Grundstruktur", "Kernlogik", "Integration", "Tests", "Cleanup"],
        "risiko_checks": ["Breaking Changes an bestehender API?", "Neue Dependencies nötig?"],
        "pflicht_schritte": ["Interface/Typen definieren", "Tests schreiben"],
    },
    "migration": {
        "phasen": ["Kompatibilitäts-Check", "Parallelbetrieb", "Schrittweise Migration", "Verifikation", "Altsystem entfernen"],
        "risiko_checks": ["Rollback-Strategie?", "Datenverlust möglich?", "Abwärtskompatibilität?"],
        "pflicht_schritte": ["Neue Version installieren", "Module einzeln migrieren", "Nach jedem Modul testen"],
    },
    "bugfix": {
        "phasen": ["Reproduktion", "Ursachenanalyse", "Fix", "Regressionstest", "Cleanup"],
        "risiko_checks": ["Gleicher Bug an anderen Stellen?", "Seiteneffekte des Fix?"],
        "pflicht_schritte": ["Fehlschlagenden Test schreiben", "Fix implementieren", "Test muss grün werden"],
    },
    "testing": {
        "phasen": ["Coverage-Analyse", "Priorisierung", "Test-Erstellung", "Verifikation"],
        "risiko_checks": ["Flaky Tests?", "Externe Abhängigkeiten gemockt?"],
        "pflicht_schritte": ["Coverage-Report erzeugen", "Kritische Pfade identifizieren", "Coverage erneut messen"],
    },
    "cleanup": {
        "phasen": ["Bestandsaufnahme", "Priorisierung", "Aufräumen", "Verifikation"],
        "risiko_checks": ["Breaking Changes durch Dependency-Updates?"],
        "pflicht_schritte": ["Linter laufen lassen", "Unused imports/deps entfernen", "Tests laufen lassen"],
    },
    "devops": {
        "phasen": ["Ist-Zustand", "Konfiguration", "Test", "Deployment-Check"],
        "risiko_checks": ["Credentials/Secrets im Code?", "Produktivsystem betroffen?"],
        "pflicht_schritte": ["Config-Dateien erstellen", "Lokal testen", "Dry-Run"],
    },
    "documentation": {
        "phasen": ["Bestandsaufnahme", "Struktur", "Inhalt", "Review"],
        "risiko_checks": ["Docs konsistent mit aktuellem Code?"],
        "pflicht_schritte": ["Bestehende Docs lesen", "Lücken identifizieren", "Konsistenz prüfen"],
    },
}


# ════════════════════════════════════════════════════════════
#  AB HIER NICHTS ÄNDERN — Dateien generieren
# ════════════════════════════════════════════════════════════

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
                            'then echo "NIGHTSHIFT BLOCKED: Destruktiver Befehl" >&2; exit 2; fi; '
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
                        "command": "bash -c 'echo \"$(date -Iseconds) heartbeat\" >> /tmp/nightshift-heartbeat.log'",
                    }
                ],
            }
        ],
        "SessionStart": [
            {
                "matcher": "compact",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "echo 'NACH COMPACT: Lies runbook.md sofort erneut. "
                            "Finde den nächsten nicht abgehakten Punkt (- [ ]). "
                            "Arbeite dort weiter. Hake erledigte Schritte ab (- [x]).'"
                        ),
                    }
                ],
            }
        ],
        "Stop": [
            {
                "matcher": "",
                "hooks": [
                    {
                        "type": "command",
                        "command": (
                            "bash -c '"
                            "RUNBOOK=\"runbook.md\"; "
                            "[ -f \"$RUNBOOK\" ] || exit 0; "
                            "DONE=$(grep -c \"\\[x\\]\" \"$RUNBOOK\" 2>/dev/null || echo 0); "
                            ""
                            "# Stall detection: 3 checks without progress = warning"
                            " PROGRESS_FILE=\"/tmp/nightshift-progress\"; "
                            "STALL_FILE=\"/tmp/nightshift-stall\"; "
                            "LAST_DONE=$(cat \"$PROGRESS_FILE\" 2>/dev/null || echo 0); "
                            "echo \"$DONE\" > \"$PROGRESS_FILE\"; "
                            "if [ \"$DONE\" -eq \"$LAST_DONE\" ] && [ \"$DONE\" -gt 0 ]; then "
                            "STALL=$(($(cat \"$STALL_FILE\" 2>/dev/null || echo 0) + 1)); "
                            "echo \"$STALL\" > \"$STALL_FILE\"; "
                            "if [ \"$STALL\" -ge 3 ]; then "
                            "echo \"STALL WARNING: Kein Fortschritt seit 3 Checks ($DONE Schritte). "
                            "Moeglicher Loop. Pruefe ob du an einem Schritt haengst. "
                            "Wenn ein Test wiederholt fehlschlaegt: Lies das Fehler-Budget in runbook.md. "
                            "Ueberspringe den Schritt wenn das Budget es erlaubt.\"; "
                            "fi; "
                            "else echo 0 > \"$STALL_FILE\"; fi; "
                            ""
                            "# Checkpoint every 5 steps"
                            " if [ \"$DONE\" -gt 0 ] && [ $(($DONE % 5)) -eq 0 ] && [ \"$DONE\" -ne \"$LAST_DONE\" ]; then "
                            "echo \"CHECKPOINT ($DONE Schritte erledigt): "
                            "Lies die Autonomiebereiche und Fehler-Toleranz in runbook.md erneut. "
                            "Pruefe ob du noch auf Kurs bist. "
                            "Naechster offener Punkt: $(grep -m1 \"\\- \\[ \\]\" \"$RUNBOOK\" 2>/dev/null || echo FERTIG)\"; "
                            "fi; exit 0'"
                        ),
                    }
                ],
            }
        ],
    }
}

RUN_SH = f"""#!/bin/bash
set -euo pipefail

# PID-Lock: Verhindert doppelten Start
PIDFILE="/tmp/nightshift.pid"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "❌ Nightshift läuft bereits (PID $(cat "$PIDFILE"))"
    echo "   Beenden: kill $(cat "$PIDFILE")"
    exit 1
fi
echo $$ > "$PIDFILE"

# Graceful Shutdown
cleanup() {{
    echo ""
    echo "⏹  Nightshift wird beendet... ($(date))"
    rm -f "$PIDFILE"
    exit 0
}}
trap cleanup SIGTERM SIGINT EXIT

LOGFILE="/tmp/nightshift-$(date +%Y%m%d-%H%M%S).log"
echo "=== Claude Nightshift Start: $(date) ===" | tee "$LOGFILE"
echo "Projekt: {PROJEKTPFAD}"
echo "Aufgabe: {AUFGABE_TITEL}"
echo "Genre:   {GENRE}"
echo "Log:     $LOGFILE"
echo "PID:     $$"
echo ""
echo "⚠️  KOSTEN-HINWEIS: Dieser Run erzeugt API-Calls."
echo "   Überwache dein Anthropic-Dashboard."
echo ""

> /tmp/nightshift-heartbeat.log

cd "{PROJEKTPFAD}"

if ! git diff --quiet 2>/dev/null || ! git diff --staged --quiet 2>/dev/null; then
    echo "⚠️  Uncommitted changes gefunden. Empfehlung: git stash"
fi

claude -p \\
  "Lies runbook.md und arbeite alle Punkte sequentiell ab. \\
   Hake jeden erledigten Schritt mit [x] ab. \\
   Wenn du unsicher bist, lies CLAUDE.md fuer Konventionen. \\
   Nach jeder Phase: pruefe runbook.md ob alles abgehakt ist. \\
   Am Ende: git add -A && git commit -m '{AUFGABE_KURZ}'" \\
  --dangerously-skip-permissions \\
  --output-format stream-json \\
  2>&1 | tee -a "$LOGFILE"

echo ""
echo "=== Claude Nightshift Ende: $(date) ===" | tee -a "$LOGFILE"
"""

RUN_BG_SH = f"""#!/bin/bash
echo "Starte Nightshift im Hintergrund..."
nohup bash "{PROJEKTPFAD}/nightshift-run.sh" > /tmp/nightshift-nohup.log 2>&1 &
PID=$!
echo "Laeuft als PID $PID"
echo "Log:      /tmp/nightshift-nohup.log"
echo "Watchdog: ./nightshift-watchdog.sh"
echo "Beenden:  kill $PID"
"""

WATCHDOG_SH = """#!/bin/bash
TIMEOUT=${1:-600}

echo "🔍 Nightshift Watchdog aktiv (Timeout: ${TIMEOUT}s)"
echo ""

while true; do
  HEARTBEAT="/tmp/nightshift-heartbeat.log"

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

  if [ $DIFF -gt $TIMEOUT ]; then
    echo "⚠️  $(date +%H:%M:%S): KEIN HEARTBEAT seit ${DIFF}s!"
    osascript -e 'display notification "Claude haengt!" with title "Nightshift"' 2>/dev/null || true
  else
    echo "✅ $(date +%H:%M:%S): OK (${DIFF}s)"
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

(allow file-read* file-write* (subpath "{PROJEKTPFAD}"))
(allow file-read* file-write* (subpath "/tmp"))
(allow file-read* file-write* (subpath "/private/tmp"))

(allow file-read* (subpath "{HOMEDIR}/.claude"))
(allow file-read* (subpath "{HOMEDIR}/.npm-global"))
(allow file-read* (subpath "{HOMEDIR}/.config"))
(allow file-read* (subpath "{HOMEDIR}/.bun"))
(allow file-read* (subpath "{HOMEDIR}/.nvm"))
(allow file-read* (subpath "{HOMEDIR}/.cargo"))

(allow network-outbound (remote tcp "*:443"))
(allow system-socket)
(allow sysctl-read)
(allow mach-lookup)
"""

CLAUDE_NIGHTSHIFT_MD = f"""## Nightshift-Konventionen
- Runbook liegt in `runbook.md` — nach jedem /compact erneut lesen
- Erledigte Schritte mit `[x]` abhaken, nicht loeschen
- `{TESTBEFEHL}` vor jedem Commit ausfuehren
- Bei Unsicherheit: konservativer Ansatz, lieber weniger aendern
- Keine Dateien ausserhalb des Projektordners aendern
- Stack: {STACK_INFO}
- Genre: {GENRE}

## Run-Gedaechtnis
- Lies `decisions.md` falls vorhanden — enthaelt Architektur-Entscheidungen vorheriger Runs
- Dokumentiere eigene Entscheidungen am Ende in `decisions.md` (erstellen falls nicht vorhanden)
- Format: Datum, Entscheidung, Begruendung
"""

# Genre-Info für README
genre_info = GENRE_TEMPLATES.get(GENRE, {})
genre_phasen = ", ".join(genre_info.get("phasen", ["Unbekannt"]))
genre_risiken = "\n".join(f"  - {r}" for r in genre_info.get("risiko_checks", []))

README = f"""# Nightshift Setup: {AUFGABE_TITEL}

**Genre:** {GENRE}
**Phases:** {genre_phasen}

## Quick Start

```bash
# 1. Unzip
unzip nightshift-setup.zip

# 2. Copy into project
cd {PROJEKTPFAD}
cp -r /path/to/nightshift-setup/.claude .
cp /path/to/nightshift-setup/runbook.md .
cp /path/to/nightshift-setup/nightshift-*.sh .
cp /path/to/nightshift-setup/nightshift-sandbox.sb .
chmod +x nightshift-*.sh

# 3. Append to CLAUDE.md
cat /path/to/nightshift-setup/CLAUDE-nightshift.md >> CLAUDE.md

# 4. COMMIT FIRST!
git add -A && git commit -m "Checkpoint before Nightshift"

# 5. Run
./nightshift-run.sh                                        # Foreground
./nightshift-run-bg.sh                                     # Background
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh  # With sandbox
```

## Risk Checks ({GENRE})
{genre_risiken}

## Watchdog

```bash
./nightshift-watchdog.sh        # Alert after 10 min without heartbeat
./nightshift-watchdog.sh 300    # Alert after 5 min
```

## Emergency

```bash
git checkout .                          # Revert all changes
git stash                               # Stash changes for review
pkill -f "claude.*dangerously"          # Kill Claude process
```

---

Autonomy zones and error budget inspired by [AlpiType — Solving the AI Agent Approval Loop](https://alpitype.de/insights/ki-agenten-approval-loop/)

**Disclaimer:** This project was created privately, to the best of the author's knowledge. Use at your own risk. No warranty of completeness, correctness, or fitness for any particular purpose.
"""


# ════════════════════════════════════════════════════════════
#  VALIDIEREN UND ZIP BAUEN
# ════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Validierung
    passed, total, checks, vague_steps = validate_runbook(RUNBOOK)
    print_validation(passed, total, checks, vague_steps)

    if passed < total:
        print(f"\n⚠️  Validierung: {passed}/{total} — Runbook hat Probleme!")
        print("   ZIP wird trotzdem erstellt, aber bitte Runbook nachbessern.\n")
    else:
        print(f"\n✅ Validierung: {passed}/{total} — Runbook ist bereit!\n")

    # ZIP
    ZIP_PATH = "/mnt/user-data/outputs/nightshift-setup.zip"

    files = {
        "runbook.md": RUNBOOK,
        ".claude/settings.json": json.dumps(SETTINGS, indent=2, ensure_ascii=False),
        "nightshift-run.sh": RUN_SH,
        "nightshift-run-bg.sh": RUN_BG_SH,
        "nightshift-watchdog.sh": WATCHDOG_SH,
        "nightshift-sandbox.sb": SANDBOX_SB,
        "CLAUDE-nightshift.md": CLAUDE_NIGHTSHIFT_MD,
        "README-nightshift.md": README,
    }

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for filename, content in files.items():
            zf.writestr(f"nightshift-setup/{filename}", content)

    print(f"✅ nightshift-setup.zip erstellt: {ZIP_PATH}")
    print(f"   Genre:    {GENRE}")
    print(f"   Aufgabe:  {AUFGABE_TITEL}")
    print(f"   Projekt:  {PROJEKTPFAD}")
    print(f"   Dateien:  {len(files)}")
    print(f"   Schritte: {len(re.findall(r'^- \[ \]', RUNBOOK, re.MULTILINE))}")
