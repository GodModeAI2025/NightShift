#!/usr/bin/env python3
"""
Claude Nightshift — ZIP Builder
Erzeugt alle Dateien und packt sie als nightshift-setup.zip
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

# Kostenbudget des Laufs. Der Runner bricht ab, sobald die Schaetzung darueber
# liegt. Zur Laufzeit ueberschreibbar: NIGHTSHIFT_BUDGET_USD im Runner.
BUDGET_USD = os.environ.get("NIGHTSHIFT_BUDGET_USD", "25.00")
# Zusaetzliche Obergrenze in Tokens (Ein- plus Ausgabe). 0 heisst: keine.
BUDGET_TOKENS = os.environ.get("NIGHTSHIFT_BUDGET_TOKENS", "0")

# Preise je Million Tokens, Stand siehe PREISE_STAND. Die Schaetzung des
# Runners ist nur so gut wie diese Tabelle; ein neuer Preis gehoert hierher
# und nicht in den Bash-String. Zuordnung ueber den Modellnamen aus der
# stream-json-Ausgabe: der erste passende Schluessel gewinnt.
PREISE_STAND = "2026-06-24"
PREISE = [
    # Schluessel, Eingabe $/1M, Ausgabe $/1M. Der erste passende
    # Schluessel gewinnt, deshalb stehen die genaueren Namen oben:
    # "sonnet-4-6" muss vor "sonnet" liegen, sonst rechnet der Zaehler
    # Sonnet 4.6 zum billigeren Sonnet-Tarif und das Budget greift zu
    # spaet.
    ("fable", 10.00, 50.00),
    ("mythos", 10.00, 50.00),
    ("opus", 5.00, 25.00),
    ("sonnet-4-6", 3.00, 15.00),
    ("sonnet", 2.00, 10.00),
    ("haiku", 1.00, 5.00),
]
# Passt kein Schluessel, rechnet der Zaehler mit der teuersten Zeile mal
# diesem Faktor. Die teuerste bekannte Zeile allein genuegt nicht: ein
# Modell, das nach PREISE_STAND erscheint, kann darueber liegen, und dann
# unterschaetzt der Fallback genau die Zahl, gegen die er da ist.
PREIS_AUFSCHLAG = 2.0

# Hosts, die der Container erreichen darf. Alles andere blockt der
# Egress-Proxy. api.anthropic.com genuegt fuer einen Lauf mit
# ANTHROPIC_API_KEY. Wer sich im Container per OAuth anmeldet, braucht
# zusaetzlich platform.claude.com und claude.ai.
NETZ_ALLOWLIST = ["api.anthropic.com"]

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

# ── PreToolUse-Hooks: rote Zone ─────────────────────────────
# Zwei Schranken, beide aus gemeinsam.py:
#   Bash                              prueft den Kommandotext
#   Write, Edit, MultiEdit, NotebookEdit  prueft den Zielpfad
# Die zweite gab es bis Welle 6 nicht. Der Hook trug nur "matcher": "Bash",
# und damit konnte ein unbeaufsichtigter Lauf jede Datei auf der Platte
# schreiben, ohne dass die Schutzschicht das ueberhaupt sah.
PRETOOLUSE = gemeinsam.pretooluse(
    "NIGHTSHIFT", "NIGHTSHIFT_PROJEKT", PROJEKTPFAD
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

# Namen, die die Isolationspruefung aus gemeinsam.py braucht.
_ISOLATION = {
    "SANDBOXVAR": "NIGHTSHIFT_SANDBOXED",
    "ALLOWVAR": "NIGHTSHIFT_ALLOW_UNSANDBOXED",
    "PROFILNAME": "nightshift",
    "PROFILDATEI": "nightshift-sandbox.sb",
    "DOCKERSKRIPT": "nightshift-docker.sh",
    "STARTSKRIPT": "nightshift-run.sh",
    "GEGENSTAND": "das Projekt",
    "GEGENSTAND_AKK": "das Projekt",
    "PFADSHELL": "PROJEKT",
}

RUN_SH = (
r"""#!/bin/bash
set -uo pipefail

# Der Projektpfad ist beweglich. Im Container liegt das Projekt unter
# /project, nicht unter dem Pfad, der beim Generieren gesetzt war; das
# Dockerfile setzt NIGHTSHIFT_PROJEKT entsprechend.
PROJEKT="${NIGHTSHIFT_PROJEKT:-@@PROJEKTPFAD@@}"
RUNID="$(date +%Y%m%d-%H%M%S)"
START="$(date -Iseconds 2>/dev/null || date)"
ZIEL="$PROJEKT/nightshift-receipts/$RUNID"
KOSTENDATEI="$ZIEL/cost.json"

# Budget. Zur Laufzeit ueberschreibbar, damit ein einzelner Lauf teurer
# oder billiger sein darf, ohne das Setup neu zu bauen.
BUDGET_USD="${NIGHTSHIFT_BUDGET_USD:-@@BUDGET_USD@@}"
BUDGET_TOKENS="${NIGHTSHIFT_BUDGET_TOKENS:-@@BUDGET_TOKENS@@}"

@@ISOLATION_MESSEN@@
# PID-Lock: Verhindert doppelten Start
# Denselben Ort wie der Watchdog. Der liest NIGHTSHIFT_PIDDATEI, und wenn
# der Runner stattdessen fest /tmp/nightshift.pid schreibt, sucht der
# Watchdog bei gesetzter Variable an einer Stelle, an der nie etwas steht,
# und haelt jeden Lauf fuer beendet.
PIDFILE="${NIGHTSHIFT_PIDDATEI:-/tmp/nightshift.pid}"
if [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
    echo "Nightshift laeuft bereits (PID $(cat "$PIDFILE"))"
    echo "   Beenden: kill $(cat "$PIDFILE")"
    exit 1
fi
echo $$ > "$PIDFILE"

# Diese drei Namen muessen vor den Traps stehen: der Signalpfad greift
# darauf zu, und unter "set -u" waere eine ungesetzte Variable dort ein
# Fehler mitten im Beenden.
CLAUDE_PIDDATEI="/tmp/nightshift-claude-$$.pid"
RCDATEI="/tmp/nightshift-rc-$$"
STOPMARKER="/tmp/nightshift-budget-stop-$$"
PIPELINE_PGID=""
# Frist, die die Pipeline nach dem Budget-Stop noch bekommt.
STOPFRIST="${NIGHTSHIFT_STOPFRIST:-30}"

# Claude beenden heisst: die Prozessgruppe beenden. Ein einzelnes
# kill -TERM auf die PID laesst umgehaengte Enkel am Leben, und die
# halten den Pipe-Deskriptor offen; der Lauf haengt dann, ohne dass noch
# Geld fliesst. Der Runner startet claude deshalb mit eigener Gruppe
# (set -m), die Gruppen-ID ist die PID.
claude_gruppe_beenden() {
    NS_PID=$(cat "$CLAUDE_PIDDATEI" 2>/dev/null)
    case "${NS_PID:-}" in ''|*[!0-9]*) return 0 ;; esac
    kill -TERM -- "-$NS_PID" 2>/dev/null || kill -TERM "$NS_PID" 2>/dev/null
    sleep 3
    kill -KILL -- "-$NS_PID" 2>/dev/null || kill -KILL "$NS_PID" 2>/dev/null
    return 0
}

pipeline_beenden() {
    case "${PIPELINE_PGID:-}" in ''|*[!0-9]*) return 0 ;; esac
    kill -TERM -- "-$PIPELINE_PGID" 2>/dev/null
    sleep 1
    kill -KILL -- "-$PIPELINE_PGID" 2>/dev/null
    return 0
}

# Graceful Shutdown, Exit-Code bleibt erhalten. Der Receipt entsteht hier
# und damit auch dann, wenn der Lauf abgebrochen wurde.
cleanup() {
    RC=${1:-$?}
    trap - EXIT
    echo ""
    echo "Nightshift wird beendet (Exit-Code $RC)... ($(date))"
    rm -f "$PIDFILE"
    NS_RUNID="$RUNID" NS_START="$START" NS_EXIT="$RC" \
    NS_ISOLATION="$ISOLATION" NS_KOSTEN="$KOSTENDATEI" NS_ZIEL="$ZIEL" \
    NS_GENRE="@@GENRE@@" NS_AUFGABE="@@AUFGABE_TITEL@@" \
    NS_RUNBOOK="$PROJEKT/runbook.md" NS_STALL="/tmp/nightshift-stall" \
        bash "$PROJEKT/nightshift-receipt.sh" || true
    exit "$RC"
}

# Auf ein Signal wird zuerst Claude beendet und erst danach der Receipt
# geschrieben. Umgekehrt haette der Bediener eine Nacht fuer beendet
# gehalten, waehrend claude --dangerously-skip-permissions weiterlief.
signal_abbruch() {
    trap - EXIT SIGTERM SIGINT
    echo ""
    echo "Signal empfangen. Claude wird beendet, danach kommt der Receipt."
    claude_gruppe_beenden
    pipeline_beenden
    cleanup "$1"
}
trap 'signal_abbruch 143' SIGTERM
trap 'signal_abbruch 130' SIGINT
trap cleanup EXIT

LOGFILE="/tmp/nightshift-$RUNID.log"
echo "=== Claude Nightshift Start: $(date) ===" | tee "$LOGFILE"
echo "Projekt:   $PROJEKT"
echo "Aufgabe:   @@AUFGABE_TITEL@@"
echo "Genre:     @@GENRE@@"
echo "Isolation: $ISOLATION"
echo "Budget:    $BUDGET_USD USD"
echo "Log:       $LOGFILE"
echo "Receipt:   $ZIEL"
echo "PID:       $$"
echo ""

@@ISOLATION_ABBRUCH@@
if [ "$ISOLATION" = "docker" ] && [ -z "${ANTHROPIC_API_KEY:-}" ] \
   && [ ! -f "${HOME:-/home/node}/.claude/.credentials.json" ]; then
    echo "HINWEIS: Im Container ist weder ANTHROPIC_API_KEY gesetzt noch eine"
    echo "   Anmeldung im Home-Volume vorhanden. Claude bricht dann ab."
fi

echo ""
echo "KOSTEN: Der Lauf wird mitgezaehlt und bei $BUDGET_USD USD gestoppt."
echo "   Die Schaetzung steht in $KOSTENDATEI."
echo ""

mkdir -p "$ZIEL"
> /tmp/nightshift-heartbeat.log

cd "$PROJEKT" || { echo "Projektpfad $PROJEKT nicht gefunden"; exit 4; }

if ! git diff --quiet 2>/dev/null || ! git diff --staged --quiet 2>/dev/null; then
    echo "Uncommitted changes gefunden. Empfehlung: git stash"
fi

echo 0 > "$RCDATEI"

# Claude laeuft im Hintergrund, damit seine PID bekannt ist: ohne sie
# koennte der Kostenzaehler den Lauf nicht beenden. Der Exit-Code geht
# ueber eine Datei, weil das Ende der Pipeline dem Zaehler gehoert.
#
# "set -m" gibt claude eine eigene Prozessgruppe. Nur so trifft der
# Budget-Stop auch Enkelprozesse; ohne sie ueberlebt ein umgehaengtes
# Kind den Stop und haelt die Pipe offen.
#
# --verbose ist nicht schmueckend: Claude Code lehnt
# "--print --output-format stream-json" ohne diese Option ab und beendet
# sich mit 1. Ohne sie laeuft ueberhaupt kein Lauf.
#
# </dev/null: in einer eigenen Prozessgruppe im Hintergrund waere ein
# Lesen vom Terminal ein SIGTTIN und damit eine Nacht, die stillsteht,
# ohne zu enden. Gemessen wurde das mit dieser Version nicht, der Prompt
# steht ja im Argument; die Umleitung nimmt den Fall trotzdem heraus.
#
# Die Pipeline laeuft im Hintergrund und der Runner wartet mit "wait".
# Ein Trap greift waehrend eines Vordergrund-Kommandos erst, wenn dieses
# fertig ist; waehrend "wait" greift er sofort. Genau davon haengt ab, ob
# "kill $PID" die Nacht wirklich beendet.
set -m
{
    set -m
    claude -p \
      "Lies runbook.md und arbeite alle Punkte sequentiell ab. \
       Hake jeden erledigten Schritt mit [x] ab. \
       Wenn du unsicher bist, lies CLAUDE.md fuer Konventionen. \
       Nach jeder Phase: pruefe runbook.md ob alles abgehakt ist. \
       Am Ende: git add -A && git commit -m '@@AUFGABE_KURZ@@'" \
      --dangerously-skip-permissions \
      --output-format stream-json \
      --verbose \
      </dev/null 2>&1 &
    NS_CLAUDE=$!
    echo "$NS_CLAUDE" > "$CLAUDE_PIDDATEI"
    set +m
    wait "$NS_CLAUDE"
    echo $? > "$RCDATEI"
} | tee -a "$LOGFILE" \
  | bash "$PROJEKT/nightshift-cost.sh" \
        "$KOSTENDATEI" "$BUDGET_USD" "$BUDGET_TOKENS" "$CLAUDE_PIDDATEI" "$STOPMARKER" &
PIPELINE_PID=$!
PIPELINE_PGID=$(jobs -p %+ 2>/dev/null | head -1)
case "${PIPELINE_PGID:-}" in ''|*[!0-9]*) PIPELINE_PGID="" ;; esac
set +m

# Harte Zeitgrenze nach dem Budget-Stop. Sobald der Marker liegt, hat die
# Pipeline STOPFRIST Sekunden; danach wird sie beendet. Ein Lauf, der nach
# dem Stop nicht endet, kostet zwar nichts mehr, aber der Receipt kommt
# nicht und ein Watchdog sieht eine Nacht ohne Ende.
(
    while kill -0 "$PIPELINE_PID" 2>/dev/null; do
        if [ -f "$STOPMARKER" ]; then
            sleep "$STOPFRIST"
            if kill -0 "$PIPELINE_PID" 2>/dev/null; then
                echo "STOPFRIST: Pipeline haengt ${STOPFRIST}s nach dem Budget-Stop, wird beendet." >&2
                claude_gruppe_beenden
                pipeline_beenden
            fi
            exit 0
        fi
        sleep 1
    done
) &
WACHHUND_PID=$!

wait "$PIPELINE_PID"
kill "$WACHHUND_PID" 2>/dev/null
wait "$WACHHUND_PID" 2>/dev/null

CLAUDE_RC=$(cat "$RCDATEI" 2>/dev/null || echo 1)
case "$CLAUDE_RC" in ''|*[!0-9]*) CLAUDE_RC=1 ;; esac

if [ -f "$STOPMARKER" ]; then
    echo ""
    echo "BUDGET-STOP: Der Lauf wurde bei $BUDGET_USD USD beendet."
    CLAUDE_RC=9
fi

rm -f "$CLAUDE_PIDDATEI" "$RCDATEI" "$STOPMARKER"

echo ""
if [ "$CLAUDE_RC" -eq 0 ]; then
    echo "=== Claude Nightshift Ende: $(date) ===" | tee -a "$LOGFILE"
else
    echo "=== Claude Nightshift ABGEBROCHEN: $(date) (Exit-Code $CLAUDE_RC) ===" | tee -a "$LOGFILE"
fi
exit $CLAUDE_RC
"""
    .replace("@@PROJEKTPFAD@@", PROJEKTPFAD)
    .replace("@@AUFGABE_TITEL@@", AUFGABE_TITEL)
    .replace("@@AUFGABE_KURZ@@", AUFGABE_KURZ)
    .replace("@@GENRE@@", GENRE)
    .replace("@@BUDGET_USD@@", BUDGET_USD)
    .replace("@@BUDGET_TOKENS@@", BUDGET_TOKENS)
    # Die Isolationspruefung ist in beiden Runnern dieselbe. Sie steht in
    # gemeinsam.py, damit eine Verschaerfung nicht in einem der beiden
    # Skills haengen bleibt.
    .replace("@@ISOLATION_MESSEN@@", gemeinsam.isolation_messen(_ISOLATION))
    .replace("@@ISOLATION_ABBRUCH@@", gemeinsam.isolation_abbruch(_ISOLATION))
)

RUN_BG_SH = f"""#!/bin/bash
echo "Starte Nightshift im Hintergrund..."
PROJEKT="${{NIGHTSHIFT_PROJEKT:-{PROJEKTPFAD}}}"
nohup bash "$PROJEKT/nightshift-run.sh" > /tmp/nightshift-nohup.log 2>&1 &
PID=$!
echo "Laeuft als PID $PID"
echo "Log:      /tmp/nightshift-nohup.log"
echo "Watchdog: ./nightshift-watchdog.sh"
echo "Beenden:  kill $PID"
"""

_WATCHDOG = {
    "MARKE": "Nightshift",
    "AKTIONVAR": "NIGHTSHIFT_WATCHDOG_AKTION",
    "NEUSTARTVAR": "NIGHTSHIFT_WATCHDOG_NEUSTARTS",
    "FRISTVAR": "NIGHTSHIFT_WATCHDOG_FRIST",
    "PIDVAR": "NIGHTSHIFT_PIDDATEI",
    "PIDDATEI": "/tmp/nightshift.pid",
    "STARTSKRIPT": "nightshift-run-bg.sh",
}

WATCHDOG_SH = """#!/bin/bash
TIMEOUT=${1:-600}
HEARTBEAT="${NIGHTSHIFT_HEARTBEAT:-/tmp/nightshift-heartbeat.log}"
@@REAKTION@@
echo "🔍 Nightshift Watchdog aktiv (Timeout: ${TIMEOUT}s, Aktion: $AKTION)"
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

  if [ $DIFF -gt $TIMEOUT ]; then
    echo "⚠️  $(date +%H:%M:%S): KEIN HEARTBEAT seit ${DIFF}s!"
    osascript -e 'display notification "Claude haengt!" with title "Nightshift"' 2>/dev/null || true
    stillstand_behandeln
  else
    echo "✅ $(date +%H:%M:%S): OK (${DIFF}s)"
  fi

  sleep 60
done
""".replace("@@REAKTION@@", gemeinsam.watchdog_reaktion(_WATCHDOG))

SANDBOX_SB = gemeinsam.sandbox_profil(
    dict(
        _ISOLATION,
        HOME=HOMEDIR,
        HOSTPFAD=PROJEKTPFAD,
        FREIGABENAME="Projektfreigabe",
    )
)

# ── Docker: der Standardweg fuer Isolation ──────────────────
# Ein Dockerfile mit zwei Zielen. "runner" fuehrt Claude aus und haengt in
# einem Netz, das nur den Proxy erreicht. "egress" ist dieser Proxy und
# laesst ausschliesslich die Hosts aus NETZ_ALLOWLIST durch. Damit ist der
# Lauf nicht nur beim Schreiben begrenzt (das kann das Seatbelt-Profil auch),
# sondern auch beim Lesen und beim Abfluss nach draussen.
# ── Container: Gehaeuse aus gemeinsam.py ────────────────────
# Dockerfile, Compose-Datei und Startskript stehen einmal in gemeinsam.py
# und werden hier mit den Nightshift-Namen gefuellt. 24x7 fuellt dieselben
# Vorlagen mit seinen eigenen. Was sich unterscheidet, ist die Wortliste,
# nicht die Haertung.
_CONTAINER = {
    "TITEL": "Nightshift",
    "MOUNT": "/project",
    "DOCKERSKRIPT": "nightshift-docker.sh",
    "STARTSKRIPT": "nightshift-run.sh",
    "SANDBOXVAR": "NIGHTSHIFT_SANDBOXED",
    "PFADVAR": "NIGHTSHIFT_PROJEKT",
    "GEGENSTAND": "das Projekt",
    "DIENST": "nightshift",
    "HOSTPFAD": PROJEKTPFAD,
    "SPEICHER": "4g",
    "READMENAME": "README-nightshift.md",
    "ZWECK": "Baut den Container und laesst den Nightshift darin laufen.",
    "KOPF": "Nightshift, isoliert. Der Standardweg auf Linux und macOS.",
    "WERKZEUGNOTIZ": (
        "# Der Budget-Stop selbst braucht kein Werkzeug mehr: er beendet die\n"
        "# Prozessgruppe mit dem kill der Shell."
    ),
    "ALLOWLIST": gemeinsam.allowlist_argumente(NETZ_ALLOWLIST),
    "ZUSATZENV": (
        '\n      NIGHTSHIFT_BUDGET_USD: "${NIGHTSHIFT_BUDGET_USD:-%s}"' % BUDGET_USD
    ),
}

DOCKERFILE = gemeinsam.dockerfile(_CONTAINER)
DOCKER_COMPOSE = gemeinsam.compose(_CONTAINER)
DOCKER_SH = gemeinsam.docker_sh(_CONTAINER, gemeinsam.DOCKER_SH_LAUF)


# ── Cost Governor: erst messen, dann stoppen ────────────────
_PREISE_AWK = ";".join(
    "%s:%s:%s" % (schluessel, ein, aus) for schluessel, ein, aus in PREISE
)

COST_SH = gemeinsam.cost_sh("nightshift")


# ── Morning Receipt ─────────────────────────────────────────
# Laeuft im EXIT-Trap des Runners, also auch nach einem Abbruch. Felder,
# die niemand ermitteln kann, stehen als "unbekannt" drin und nicht als 0
# oder null: eine Null waere eine Aussage, die niemand geprueft hat.
RECEIPT_SH = gemeinsam.receipt_sh("nightshift", "nightshift-run.sh")



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
NETZ_ALLOWLIST_TEXT = ", ".join("`%s`" % host for host in NETZ_ALLOWLIST)
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
cp /path/to/nightshift-setup/runbook.md .
cp /path/to/nightshift-setup/nightshift-*.sh .
cp /path/to/nightshift-setup/nightshift-sandbox.sb .
chmod +x nightshift-*.sh

# 2a. Hook configuration, an existing settings.json is never overwritten
if [ -e .claude/settings.json ]; then
  echo "STOP: .claude/settings.json exists, merge it (see below)"
else
  mkdir -p .claude
  cp -R /path/to/nightshift-setup/.claude/. .claude/
fi
test -f .claude/settings.json && echo "hooks in place" || echo "WARNING: no hooks"

# 3. Append to CLAUDE.md
cat /path/to/nightshift-setup/CLAUDE-nightshift.md >> CLAUDE.md

# 4. COMMIT FIRST!
git add -A && git commit -m "Checkpoint before Nightshift"

# 5. Run, isolated (the default)
export ANTHROPIC_API_KEY=sk-ant-...
./nightshift-docker.sh
```

## Isolation

`nightshift-run.sh` refuses to start without isolation. The state is
**measured, not declared** — an environment variable cannot unlock it:

| State | How it is reached | How it is verified | What it means |
|---|---|---|---|
| `docker` | `./nightshift-docker.sh` | `/.dockerenv`, `/run/.containerenv`, `/proc/1/cgroup` or an overlay root | Only `{PROJEKTPFAD}` is mounted, as `/project`. No home directory, no `~/.claude`, no neighbouring projects. Outbound traffic goes through a proxy that allows {NETZ_ALLOWLIST_TEXT} and answers everything else with 403. |
| `seatbelt` | `sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh` | the runner can list the project but not `/Users` — under the profile that read is denied | macOS only, kernel-enforced writes. Reads of the rest of the system and outbound traffic on 443 stay open. Apple has deprecated `sandbox-exec`. |
| `keine` | plain `./nightshift-run.sh` | neither probe answered | The run aborts with exit code 3. Deliberate opt-out: `NIGHTSHIFT_ALLOW_UNSANDBOXED=1`, and the receipt then says `keine`. |

`NIGHTSHIFT_SANDBOXED` is a cross-check, not a switch: if what it claims
differs from what was measured, the run aborts with exit code 3. Setting it
grants nothing.

The state ends up in the receipt, so afterwards you can tell how the run was fenced.

```bash
./nightshift-docker.sh                                      # Container, the default
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh    # macOS option
NIGHTSHIFT_ALLOW_UNSANDBOXED=1 ./nightshift-run.sh           # No isolation, on purpose
./nightshift-run-bg.sh                                      # Background, host
```

## The Two Barriers

`.claude/settings.json` installs two `PreToolUse` hooks. They look at
different things, and the second one is the newer of the two:

| Matcher | What it examines | What it does |
|---|---|---|
| `Bash` | the command text | blocks `rm` against dangerous targets, `sudo`, `mkfs`, `dd` to a device, `chmod 777`, `curl \| bash`, `eval` |
| `Write\|Edit\|MultiEdit\|NotebookEdit` | the target path | blocks every write outside `{PROJEKTPFAD}`, plus `.claude/settings.json` inside it |

The path guard normalises before it compares: `~/` becomes your home
directory, `.` and `..` are resolved. `{PROJEKTPFAD}/../elsewhere/x` is therefore
outside and gets blocked, and a relative path is resolved against the working
directory Claude Code sends with the call. Without `jq` neither hook can read
its input, and both then block instead of waving the call through.

The root comes from `NIGHTSHIFT_PROJEKT` at run time and defaults to `{PROJEKTPFAD}`. The container sets it to
`/project`, so the same hook fences the run there too.

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

## Budget

The run counts tokens from Claude's `stream-json` output and stops at
{BUDGET_USD} USD. Override per run:

```bash
NIGHTSHIFT_BUDGET_USD=5 ./nightshift-docker.sh
NIGHTSHIFT_BUDGET_TOKENS=2000000 ./nightshift-run.sh   # additional token ceiling
```

The dollar figure is an estimate from the price table of {PREISE_STAND}
(`nightshift-cost.sh`). Prices change; the invoice is the Anthropic
dashboard, not this file. A model name the table does not know is billed at
the most expensive known row times {PREIS_AUFSCHLAG:.1f} — the top row alone
would still undercount a model released after {PREISE_STAND}.

There is no measurement without `jq`, and none when the stream carries no
`usage` events at all — a changed output format, for instance. In both cases
the receipt says `unbekannt` instead of pretending a zero.

## Morning Receipt

Every run writes `nightshift-receipts/<run-id>/receipt.json` and
`receipt.md` — including after a crash, because it comes out of the exit
trap. Fields the run could not determine are `"unbekannt"`, never `0` or
`null`. The receipts are not committed by the run; they land in the working
tree next to your code.

## Existing .claude/settings.json

Copying would drop your own hooks, permissions, and MCP settings. Merge instead.
The command keeps your entries and appends the Nightshift hooks per event type:

```bash
jq -s '(.[0].hooks // {{}}) as $mine | (.[1].hooks // {{}}) as $new
       | (.[0] * .[1])
       | .hooks = (reduce (($mine | to_entries[]), ($new | to_entries[])) as $e
                   ({{}}; .[$e.key] = ((.[$e.key] // []) + $e.value)))' \\
  .claude/settings.json /path/to/nightshift-setup/.claude/settings.json \\
  > .claude/settings.merged.json

# read it, then take it over
mv .claude/settings.merged.json .claude/settings.json
```

## Risk Checks ({GENRE})
{genre_risiken}

## Watchdog

```bash
./nightshift-watchdog.sh                       # Alert after 10 min without heartbeat
./nightshift-watchdog.sh 300                   # Alert after 5 min
```

Detecting a stall was always there. Reacting to one is what the three actions
add. Set `NIGHTSHIFT_WATCHDOG_AKTION`:

| Action | What happens on a stall |
|---|---|
| `melden` (default) | One line on stdout and a macOS notification. Nothing is stopped. |
| `beenden` | `TERM` to the PID in `/tmp/nightshift.pid`, `KILL` after `NIGHTSHIFT_WATCHDOG_FRIST` seconds (default 20), then the watchdog exits. |
| `neustart` | The same, and then the run is started again, at most `NIGHTSHIFT_WATCHDOG_NEUSTARTS` times (default 1). |

```bash
NIGHTSHIFT_WATCHDOG_AKTION=neustart ./nightshift-watchdog.sh 600
```

**A run that ended on its own is never restarted.** The watchdog only restarts
what it just terminated itself, and it recognises that by a live PID in
`/tmp/nightshift.pid`. A budget stop ends the run, so afterwards there is no live PID
and the watchdog reports instead of restarting. Same for a crash and for a
finished run. A restart picks the runbook back up at the first unchecked item; that is what the runbook is for.

**What the watchdog does not cover:**

- **A busy loop.** The heartbeat comes from the `PostToolUse` hook. Claude
  retrying the same failing test forever keeps writing heartbeats, and to the
  watchdog that looks healthy. The `Stop` hook has a stall detector for that case, and it writes text into Claude's context rather than stopping anything.
- **A run in the container.** `/tmp` inside the container is a tmpfs of its
  own, so the heartbeat never reaches the host and a watchdog started there
  waits forever. Read `docker compose logs -f nightshift` instead.
- **The reason for the stall.** It restarts, it does not diagnose. If the run
  hangs on the same step every time, the restart budget runs out and the
  watchdog exits.
- **Being started at all.** It is a separate script in a second terminal, and
  nothing starts it for you.
- **The isolation the original run had.** The restart runs
  `nightshift-run-bg.sh`, a bare `nohup bash nightshift-run.sh`, and the new
  run inherits the watchdog's environment rather than the terminated run's.
  A run fenced by `sandbox-exec` comes back unfenced, measures `keine` and
  refuses with exit code 3. That fails closed, but it means `neustart`
  completes only for a host run whose watchdog shell carries the same
  `NIGHTSHIFT_ALLOW_UNSANDBOXED=1`.

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
    # Zielpfad ueberschreibbar, damit der Generator auch ausserhalb der
    # Claude-Umgebung schreiben kann (Tests, CI, lokale Laeufe).
    ZIP_PATH = os.environ.get(
        "NIGHTSHIFT_OUT", "/mnt/user-data/outputs/nightshift-setup.zip"
    )
    os.makedirs(os.path.dirname(ZIP_PATH) or ".", exist_ok=True)

    files = {
        "runbook.md": RUNBOOK,
        ".claude/settings.json": json.dumps(SETTINGS, indent=2, ensure_ascii=False),
        "nightshift-run.sh": RUN_SH,
        "nightshift-run-bg.sh": RUN_BG_SH,
        "nightshift-watchdog.sh": WATCHDOG_SH,
        "nightshift-cost.sh": COST_SH,
        "nightshift-receipt.sh": RECEIPT_SH,
        "nightshift-docker.sh": DOCKER_SH,
        "Dockerfile": DOCKERFILE,
        "docker-compose.yml": DOCKER_COMPOSE,
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
    # Backslashes duerfen bis Python 3.11 nicht im f-String-Ausdruck stehen,
    # deshalb steht das Muster in einer eigenen Variablen.
    offene_schritte = len(re.findall(r"^- \[ \]", RUNBOOK, re.MULTILINE))
    print(f"   Schritte: {offene_schritte}")
