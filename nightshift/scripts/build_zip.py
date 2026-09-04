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

# ── PreToolUse-Hook: rote Zone ──────────────────────────────
# Das Muster wird im Hook einfach gequotet, damit Backslashes
# unveraendert bei grep ankommen. Anfuehrungszeichen schneidet der
# Hook vor dem grep mit tr aus dem Kommando, deshalb muss das Muster
# sie nicht kennen und rm -rf "/" blockt genauso wie rm -rf /.
# Die rm-Regel trifft gefaehrliche Ziele: Wurzel, Home und dessen
# direkte Kinder, Globs, Elternpfade, Systemordner, .git. Nicht
# getroffen wird das taegliche Aufraeumen, auch nicht mit absolutem
# Pfad: "rm -rf node_modules", "rm -rf /Users/ich/projekt/dist",
# "rm -f *.log" laufen durch.
BLOCK_PATTERN = (
    "rm +(-[A-Za-z-]+ +)*("
    "/( |$)|/\\*/?( |$)|\\*/?( |$)|\\./\\*/?( |$)|\\.\\.|\\./?( |$)|\\.git/?( |$)"
    "|(~|\\$HOME|/home|/Users|/Volumes|/private)(/[^/ ]+)?/?( |$)"
    "|/(bin|boot|dev|etc|lib|opt|root|sbin|sys|usr|var"
    "|Applications|Library|System)( |/|$)"
    ")"
    "|mkfs|dd if=.* of=/dev/|sudo |chmod 777|curl.*\\|.*bash|eval |> /dev/sd"
)

# Ohne jq kann der Hook nichts pruefen. Dann blockt er und sagt warum,
# statt still durchzuwinken (fail closed).
BLOCK_CMD = (
    "bash -c '"
    "if ! command -v jq >/dev/null 2>&1; then "
    'echo "NIGHTSHIFT BLOCKED: jq nicht gefunden, Kommando nicht pruefbar" >&2; exit 2; '
    "fi; "
    "INPUT=$(cat); "
    'CMD=$(printf "%s" "$INPUT" | jq -r ".tool_input.command // empty") || '
    '{ echo "NIGHTSHIFT BLOCKED: jq konnte die Eingabe nicht lesen" >&2; exit 2; }; '
    'if [ -n "$CMD" ] && printf "%s" "$CMD" | tr -d "\\047\\042" | grep -qE '
    "'\\''" + BLOCK_PATTERN + "'\\''; then "
    'echo "NIGHTSHIFT BLOCKED: Destruktiver Befehl" >&2; exit 2; '
    "fi; "
    "exit 0'"
)


SETTINGS = {
    "hooks": {
        "PreToolUse": [
            {
                "matcher": "Bash",
                "hooks": [
                    {
                        "type": "command",
                        "command": BLOCK_CMD,
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

# ── Isolationspruefung ──────────────────────────────────────
# Isolation wird gemessen, nicht behauptet. Frueher genuegte ein Wort in
# NIGHTSHIFT_SANDBOXED, und jedes Wort kam durch; das Receipt hat dann
# einen Zustand ausgewiesen, den niemand geprueft hatte. Jetzt entscheiden
# zwei Sonden, und die Variable darf nur noch bestaetigen, was sie sehen.
isolation_messen() {
    # Container: Spuren, die die Laufzeitumgebung hinterlaesst und die
    # niemand aus der Shell heraus faelschen muss. /.dockerenv legt
    # Docker an, /run/.containerenv Podman; cgroup und der Overlay-Root
    # fangen containerd und Kubernetes.
    if [ -f /.dockerenv ] || [ -f /run/.containerenv ]; then
        echo docker; return 0
    fi
    if grep -qaE '(docker|containerd|kubepods|libpod|lxc)' /proc/1/cgroup 2>/dev/null; then
        echo docker; return 0
    fi
    if grep -qE '^overlay / ' /proc/mounts 2>/dev/null; then
        echo docker; return 0
    fi
    # Seatbelt gibt es nur auf macOS. Die Sonde liest /Users: das
    # nightshift-Profil verbietet genau das, eine nackte Shell kann es
    # immer. Die Gegenprobe auf das Projekt schliesst den Fall aus, dass
    # hier gerade ueberhaupt nichts lesbar ist.
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ] \
       && ls "$PROJEKT" >/dev/null 2>&1 \
       && ! ls /Users >/dev/null 2>&1; then
        echo seatbelt; return 0
    fi
    echo keine
}

ISOLATION="$(isolation_messen)"
BEHAUPTET="${NIGHTSHIFT_SANDBOXED:-}"
if [ -n "$BEHAUPTET" ] && [ "$BEHAUPTET" != "$ISOLATION" ]; then
    echo "NIGHTSHIFT_SANDBOXED sagt '$BEHAUPTET', gemessen wurde '$ISOLATION'."
    echo "   Die Variable schaltet keine Isolation frei, sie wird geprueft."
    echo "   Standardweg:  ./nightshift-docker.sh"
    echo "   macOS-Option: sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh"
    echo "   Abbruch."
    exit 3
fi

# PID-Lock: Verhindert doppelten Start
PIDFILE="/tmp/nightshift.pid"
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

if [ "$ISOLATION" = "keine" ]; then
    echo "WARNUNG: Dieser Lauf ist nicht isoliert."
    echo "   Claude startet mit --dangerously-skip-permissions und haette"
    echo "   Zugriff auf alles, was dein Benutzerkonto erreicht."
    echo "   Standardweg:  ./nightshift-docker.sh"
    echo "   macOS-Option: sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh"
    if [ "${NIGHTSHIFT_ALLOW_UNSANDBOXED:-0}" != "1" ]; then
        echo "   Abbruch. Bewusst ohne Isolation: NIGHTSHIFT_ALLOW_UNSANDBOXED=1 setzen."
        exit 3
    fi
    echo "   NIGHTSHIFT_ALLOW_UNSANDBOXED=1 ist gesetzt, der Lauf geht weiter."
fi

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

; Was dieses Profil leistet: es begrenzt das Schreiben auf das Projekt
; und /tmp und nimmt dem Lauf den Blick in fremde Home-Verzeichnisse.
; Es begrenzt nicht das Lesen des uebrigen Systems und nicht den
; Netzverkehr auf 443. Der Container kann beides, dieses Profil nicht.
;
; Warum das Lesen offen ist: ein Profil, das nur die Pfade unten erlaubt,
; startet auf aktuellem macOS ueberhaupt kein Programm mehr. Der
; dyld-Cache liegt heute ausserhalb dieser Liste, und schon /bin/echo
; endet dann mit SIGABRT. Ein Profil, unter dem nichts laeuft, schuetzt
; niemanden.

(allow process-fork process-exec)
(allow signal (target self))
(allow sysctl-read)
(allow mach-lookup)
(allow system-socket)
(allow network-outbound (remote tcp "*:443"))

(allow file-read*)
(deny file-read* (subpath "/Users") (subpath "/home"))
(allow file-read* (subpath "{HOMEDIR}/.claude"))
(allow file-read* (subpath "{HOMEDIR}/.npm-global"))
(allow file-read* (subpath "{HOMEDIR}/.config"))
(allow file-read* (subpath "{HOMEDIR}/.bun"))
(allow file-read* (subpath "{HOMEDIR}/.nvm"))
(allow file-read* (subpath "{HOMEDIR}/.cargo"))

; Ohne diese Geraete laeuft keine Shell: schon "irgendwas >/dev/null"
; scheitert sonst mit "Operation not permitted".
(allow file-write* (literal "/dev/null") (literal "/dev/zero")
                   (literal "/dev/random") (literal "/dev/urandom")
                   (literal "/dev/stdout") (literal "/dev/stderr")
                   (literal "/dev/tty") (literal "/dev/dtracehelper")
                   (literal "/dev/ptmx"))

(allow file-read* file-write* (subpath "/tmp"))
(allow file-read* file-write* (subpath "/private/tmp"))
; Zuletzt, damit die Projektfreigabe die Home-Sperre oben schlaegt, wenn
; das Projekt unterhalb von /Users liegt.
(allow file-read* file-write* (subpath "{PROJEKTPFAD}"))
"""

# ── Docker: der Standardweg fuer Isolation ──────────────────
# Ein Dockerfile mit zwei Zielen. "runner" fuehrt Claude aus und haengt in
# einem Netz, das nur den Proxy erreicht. "egress" ist dieser Proxy und
# laesst ausschliesslich die Hosts aus NETZ_ALLOWLIST durch. Damit ist der
# Lauf nicht nur beim Schreiben begrenzt (das kann das Seatbelt-Profil auch),
# sondern auch beim Lesen und beim Abfluss nach draussen.
_ALLOWLIST_ARGS = " ".join(
    "'^" + host.replace(".", "\\.") + "$'" for host in NETZ_ALLOWLIST
)

DOCKERFILE = r"""# syntax=docker/dockerfile:1
# Nightshift-Container. Zwei Ziele, ein File:
#   runner  laeuft Claude Code, sieht nur /project und kein offenes Netz
#   egress  Proxy mit Allowlist, der einzige Weg nach draussen
#
# Bauen und starten uebernimmt ./nightshift-docker.sh.

# ─────────────────────────── runner ───────────────────────────
FROM node:22-bookworm-slim AS runner

# git fuer die Commits, jq fuer Hook und Kostenzaehler, procps fuers
# Nachsehen, was noch laeuft, ca-certificates fuer TLS durch den Proxy.
# Der Budget-Stop selbst braucht kein Werkzeug mehr: er beendet die
# Prozessgruppe mit dem kill der Shell.
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git jq procps \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# NIGHTSHIFT_SANDBOXED ist hier nur die Gegenprobe: der Runner misst
# selbst am Kernel, ob er im Container sitzt, und bricht ab, wenn die
# Variable etwas anderes behauptet. NIGHTSHIFT_PROJEKT haelt den Pfad im
# Container beweglich: das Projekt liegt hier unter /project, nicht unter
# dem Pfad, der beim Generieren gesetzt war.
ENV NIGHTSHIFT_SANDBOXED=docker \
    NIGHTSHIFT_PROJEKT=/project \
    HOME=/home/node \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

WORKDIR /project
USER node
CMD ["bash", "/project/nightshift-run.sh"]

# ─────────────────────────── egress ───────────────────────────
FROM alpine:3.20 AS egress

RUN apk add --no-cache tinyproxy

# FilterDefaultDeny heisst: alles ist gesperrt, ausser den Zeilen in
# /etc/tinyproxy/allowlist. Die Filter greifen auch fuer CONNECT, also
# fuer HTTPS.
#
# Kein User/Group in der Konfiguration: der Container laeuft schon als
# tinyproxy (USER weiter unten). Mit den Direktiven wuerde tinyproxy einen
# setgid-Aufruf versuchen, und der scheitert, weil cap_drop ALL gesetzt ist.
RUN printf '%s\n' \
      'Port 8888' \
      'Listen 0.0.0.0' \
      'Timeout 600' \
      'Allow 0.0.0.0/0' \
      'ConnectPort 443' \
      'Filter "/etc/tinyproxy/allowlist"' \
      'FilterType ere' \
      'FilterDefaultDeny Yes' \
      'LogLevel Warning' \
      'PidFile "/tmp/tinyproxy.pid"' \
      > /etc/tinyproxy/tinyproxy.conf \
 && printf '%s\n' @@ALLOWLIST@@ > /etc/tinyproxy/allowlist

EXPOSE 8888
USER tinyproxy
CMD ["tinyproxy", "-d", "-c", "/etc/tinyproxy/tinyproxy.conf"]
""".replace("@@ALLOWLIST@@", _ALLOWLIST_ARGS)


DOCKER_COMPOSE = f"""# Nightshift, isoliert. Der Standardweg auf Linux und macOS.
#
#   ./nightshift-docker.sh
#
# Was der Container sieht: {PROJEKTPFAD} unter /project, sonst nichts vom
# Host. Kein Home, kein ~/.claude, keine Nachbarprojekte. Nach draussen
# kommt er nur ueber den Proxy und nur zu den Hosts in dessen Allowlist.

services:
  nightshift:
    build:
      context: .
      target: runner
    image: nightshift-runner
    init: true
    working_dir: /project
    command: ["bash", "/project/nightshift-run.sh"]
    volumes:
      # Der einzige Pfad vom Host. Schreibbar, weil Claude hier arbeitet.
      - "{PROJEKTPFAD}:/project"
      # Eigenes Home im Volume, damit ~/.claude des Hosts aussen bleibt.
      - "nightshift-home:/home/node"
    environment:
      # Ohne Schluessel bricht der Runner mit einer Meldung ab. Der
      # Schluessel wird nicht ins Image gebacken, er kommt aus der Umgebung
      # oder aus einer .env neben dieser Datei.
      ANTHROPIC_API_KEY: "${{ANTHROPIC_API_KEY:-}}"
      HTTPS_PROXY: "http://egress:8888"
      HTTP_PROXY: "http://egress:8888"
      NO_PROXY: "localhost,127.0.0.1"
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"
      NIGHTSHIFT_BUDGET_USD: "${{NIGHTSHIFT_BUDGET_USD:-{BUDGET_USD}}}"
    depends_on:
      - egress
    networks:
      - nightshift-intern
    # Alles ausser /project, /home/node und /tmp ist unveraenderlich.
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - "no-new-privileges:true"
    pids_limit: 512
    mem_limit: 4g

  egress:
    build:
      context: .
      target: egress
    image: nightshift-egress
    init: true
    networks:
      # Haengt in beiden Netzen und ist damit die einzige Bruecke nach
      # draussen. Was nicht in der Allowlist steht, beantwortet der Proxy
      # mit 403.
      - nightshift-intern
      - nightshift-extern
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - "no-new-privileges:true"
    mem_limit: 256m

networks:
  nightshift-intern:
    # Kein Weg nach draussen. Der Runner haengt nur hier.
    internal: true
  nightshift-extern: {{}}

volumes:
  nightshift-home: {{}}
"""


DOCKER_SH = """#!/bin/bash
# Baut den Container und laesst den Nightshift darin laufen.
set -uo pipefail

cd "$(dirname "$0")"

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "Weder 'docker compose' noch 'docker-compose' gefunden."
    echo "   Docker Compose ist der Standardweg fuer den isolierten Lauf."
    echo "   Ohne Docker: siehe README-nightshift.md, Abschnitt Isolation."
    exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ ! -f .env ]; then
    echo "ANTHROPIC_API_KEY ist nicht gesetzt und es gibt keine .env."
    echo "   export ANTHROPIC_API_KEY=sk-ant-...   oder   echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env"
    exit 1
fi

echo "Baue Container..."
"${COMPOSE[@]}" build || exit 1

echo "Starte Nightshift im Container..."
"${COMPOSE[@]}" up \\
    --abort-on-container-exit \\
    --exit-code-from nightshift
RC=$?

"${COMPOSE[@]}" down --remove-orphans >/dev/null 2>&1

echo ""
echo "Container beendet, Exit-Code $RC"
echo "Ergebnis: nightshift-receipts/ im Projekt"
exit $RC
"""


# ── Cost Governor: erst messen, dann stoppen ────────────────
_PREISE_AWK = ";".join(
    "%s:%s:%s" % (schluessel, ein, aus) for schluessel, ein, aus in PREISE
)

COST_SH = r"""#!/bin/bash
# nightshift-cost.sh — zaehlt Tokens mit und stoppt den Lauf beim Budget.
#
#   claude ... | tee -a log | ./nightshift-cost.sh <zustand> <usd> <tokens> <pidfile> <marker>
#
# Liest die stream-json-Ausgabe von Claude mit, summiert die usage-Felder
# und schreibt nach jedem Ereignis eine Zwischensumme in die Zustandsdatei.
# Ueberschreitet die Schaetzung das Budget, wird ein Marker gesetzt, der
# Claude-Prozess samt Kindern beendet und mit 9 abgebrochen.
#
# Der Zaehler bringt den Lauf nie um: kennt er das Format nicht oder fehlt
# jq, schreibt er "unbekannt" und laesst Claude weiterarbeiten.
set -uo pipefail

# Ohne das schreibt awk in einer deutschen Locale "3,5000" statt "3.5000",
# und die Zustandsdatei waere kein gueltiges JSON mehr.
export LC_ALL=C

ZUSTAND="${1:?Zustandsdatei fehlt}"
BUDGET_USD="${2:-0}"
BUDGET_TOKENS="${3:-0}"
PIDDATEI="${4:-}"
STOPMARKER="${5:-/tmp/nightshift-budget-stop}"

PREISE="@@PREISE@@"
PREISE_STAND="@@PREISE_STAND@@"
PREIS_AUFSCHLAG="@@PREIS_AUFSCHLAG@@"

mkdir -p "$(dirname "$ZUSTAND")" 2>/dev/null

zustand_unbekannt() {
    cat > "$ZUSTAND" <<ENDE
{
  "status": "unbekannt",
  "grund": "$1",
  "tokens_ein": "unbekannt",
  "tokens_aus": "unbekannt",
  "usd_geschaetzt": "unbekannt",
  "budget_usd": $BUDGET_USD,
  "budget_ueberschritten": false,
  "preise_stand": "$PREISE_STAND"
}
ENDE
}

claude_beenden() {
    [ -n "$PIDDATEI" ] || return 0
    PID=$(cat "$PIDDATEI" 2>/dev/null)
    case "${PID:-}" in ''|*[!0-9]*) return 0 ;; esac
    # Die ganze Prozessgruppe, nicht nur der Prozess und seine direkten
    # Kinder. "pkill -P" trifft genau eine Generation; ein umgehaengter
    # Enkel haelt danach den Pipe-Deskriptor und der Lauf endet nie. Der
    # Runner startet claude mit eigener Gruppe (set -m), deren
    # Gruppen-ID die PID ist.
    kill -TERM -- "-$PID" 2>/dev/null || kill -TERM "$PID" 2>/dev/null
    sleep 3
    kill -KILL -- "-$PID" 2>/dev/null || kill -KILL "$PID" 2>/dev/null
    return 0
}

if ! command -v jq >/dev/null 2>&1; then
    zustand_unbekannt "jq nicht gefunden, keine Messung moeglich"
    cat > /dev/null
    exit 0
fi

rm -f "$STOPMARKER"

jq -R -r --unbuffered '
  fromjson? // empty
  | if (.type // "") == "result"
    then ["ergebnis", ((.total_cost_usd // 0) | tostring), "0", "0", "0", "0"]
    else ( (.message // {}) as $m
           | ($m.usage // {}) as $u
           | select(($u | type) == "object" and ($u | length) > 0)
           | ($u.cache_creation // {}) as $c
           | (($c.ephemeral_5m_input_tokens // 0)) as $fuenf
           | (($u.cache_creation_input_tokens
               // ($fuenf + ($c.ephemeral_1h_input_tokens // 0)))) as $gesamt
           | [ ($m.model // "unbekannt"),
               (($u.input_tokens // 0) | tostring),
               (($u.output_tokens // 0) | tostring),
               ($fuenf | tostring),
               (($gesamt - $fuenf) | tostring),
               (($u.cache_read_input_tokens // 0) | tostring) ] )
    end
  | @tsv
' 2>/dev/null \
| awk -F'\t' \
    -v ZUSTAND="$ZUSTAND" \
    -v BUDGET_USD="$BUDGET_USD" \
    -v BUDGET_TOKENS="$BUDGET_TOKENS" \
    -v STOPMARKER="$STOPMARKER" \
    -v PREISE="$PREISE" \
    -v AUFSCHLAG="$PREIS_AUFSCHLAG" \
    -v STAND="$PREISE_STAND" '
BEGIN {
    anzahl = split(PREISE, zeilen, ";")
    for (i = 1; i <= anzahl; i++) {
        split(zeilen[i], feld, ":")
        schluessel[i] = feld[1]; preis_ein[i] = feld[2]; preis_aus[i] = feld[3]
    }
    # Cache-Schreiben kostet mehr, Cache-Lesen deutlich weniger als
    # frische Eingabe. Fuenf Minuten Haltbarkeit kosten das 1,25-fache,
    # eine Stunde das Doppelte. Ein einziger Faktor 1,25 fuer beides hat
    # einen gemessenen Lauf um 37 Prozent zu niedrig geschaetzt
    # (0.1637 statt 0.2586 USD), und das Budget greift dann zu spaet.
    # Cache-Schreiben ohne Aufschluesselung zaehlt zum teureren Satz.
    faktor_cache_5min = 1.25
    faktor_cache_1std = 2.00
    faktor_cache_lesen = 0.10
    ein = 0; aus = 0; cs5 = 0; cs1 = 0; cl = 0; usd = 0; ereignisse = 0
    gemeldet_usd = "unbekannt"
    gestoppt = 0
    fallback = 0
}
function teuerste(   i, groesster, idx) {
    groesster = -1; idx = 1
    for (i = 1; i <= anzahl; i++) if (preis_aus[i] + 0 > groesster) { groesster = preis_aus[i] + 0; idx = i }
    return idx
}
function preisindex(modell,   i, klein) {
    klein = tolower(modell)
    fallback = 0
    for (i = 1; i <= anzahl; i++) if (index(klein, schluessel[i]) > 0) return i
    # Unbekanntes Modell: teuerste bekannte Zeile mal Aufschlag. Die
    # teuerste Zeile allein reicht nicht, ein Modell nach PREISE_STAND
    # kann darueber liegen, und dann unterschaetzt gerade der Fallback.
    fallback = 1
    return teuerste()
}
function schreiben_unbekannt(grund) {
    printf("{\n") > ZUSTAND
    printf("  \"status\": \"unbekannt\",\n") > ZUSTAND
    printf("  \"grund\": \"%s\",\n", grund) > ZUSTAND
    printf("  \"tokens_ein\": \"unbekannt\",\n") > ZUSTAND
    printf("  \"tokens_aus\": \"unbekannt\",\n") > ZUSTAND
    printf("  \"tokens_gesamt\": \"unbekannt\",\n") > ZUSTAND
    printf("  \"usd_geschaetzt\": \"unbekannt\",\n") > ZUSTAND
    printf("  \"usd_gemeldet\": %s,\n",
           (gemeldet_usd == "unbekannt" ? "\"unbekannt\"" : gemeldet_usd)) > ZUSTAND
    printf("  \"budget_usd\": %s,\n", BUDGET_USD) > ZUSTAND
    printf("  \"budget_tokens\": %s,\n", BUDGET_TOKENS) > ZUSTAND
    printf("  \"budget_ueberschritten\": false,\n") > ZUSTAND
    printf("  \"ereignisse\": 0,\n") > ZUSTAND
    printf("  \"preise_stand\": \"%s\"\n", STAND) > ZUSTAND
    printf("}\n") > ZUSTAND
    close(ZUSTAND)
}
function schreiben(   ueber) {
    ueber = (gestoppt ? "true" : "false")
    printf("{\n") > ZUSTAND
    printf("  \"status\": \"gemessen\",\n") > ZUSTAND
    printf("  \"tokens_ein\": %d,\n", ein) > ZUSTAND
    printf("  \"tokens_aus\": %d,\n", aus) > ZUSTAND
    printf("  \"tokens_cache_schreiben\": %d,\n", cs5 + cs1) > ZUSTAND
    printf("  \"tokens_cache_lesen\": %d,\n", cl) > ZUSTAND
    printf("  \"tokens_gesamt\": %d,\n", ein + aus) > ZUSTAND
    printf("  \"usd_geschaetzt\": %.4f,\n", usd) > ZUSTAND
    printf("  \"usd_gemeldet\": %s,\n",
           (gemeldet_usd == "unbekannt" ? "\"unbekannt\"" : gemeldet_usd)) > ZUSTAND
    printf("  \"budget_usd\": %s,\n", BUDGET_USD) > ZUSTAND
    printf("  \"budget_tokens\": %s,\n", BUDGET_TOKENS) > ZUSTAND
    printf("  \"budget_ueberschritten\": %s,\n", ueber) > ZUSTAND
    printf("  \"ereignisse\": %d,\n", ereignisse) > ZUSTAND
    printf("  \"preise_stand\": \"%s\"\n", STAND) > ZUSTAND
    printf("}\n") > ZUSTAND
    close(ZUSTAND)
}
{
    if ($1 == "ergebnis") { gemeldet_usd = $2; schreiben(); next }
    ereignisse++
    i = preisindex($1)
    aufschlag = (fallback ? (AUFSCHLAG + 0) : 1)
    ein += $2 + 0; aus += $3 + 0; cs5 += $4 + 0; cs1 += $5 + 0; cl += $6 + 0
    usd += (($2 + 0) + ($4 + 0) * faktor_cache_5min + ($5 + 0) * faktor_cache_1std \
            + ($6 + 0) * faktor_cache_lesen) \
           / 1000000 * (preis_ein[i] + 0) * aufschlag
    usd += ($3 + 0) / 1000000 * (preis_aus[i] + 0) * aufschlag
    schreiben()
    if ((BUDGET_USD + 0) > 0 && usd >= (BUDGET_USD + 0)) {
        gestoppt = 1
        printf("BUDGET ERREICHT: %.4f USD geschaetzt, Grenze %s USD\n", usd, BUDGET_USD) > "/dev/stderr"
        printf("   Tokens: %d ein, %d aus\n", ein, aus) > "/dev/stderr"
    }
    if (!gestoppt && (BUDGET_TOKENS + 0) > 0 && (ein + aus) >= (BUDGET_TOKENS + 0)) {
        gestoppt = 1
        printf("TOKENBUDGET ERREICHT: %d Tokens, Grenze %s\n", ein + aus, BUDGET_TOKENS) > "/dev/stderr"
    }
    if (gestoppt) {
        schreiben()
        printf("stop\n") > STOPMARKER
        close(STOPMARKER)
        exit 9
    }
}
END {
    if (gestoppt) exit 9
    # Kein einziges usage-Ereignis im Strom: dann sind die Tokens
    # unbekannt und nicht null. Eine gemessene Null waere eine Aussage,
    # die hier niemand pruefen konnte, und genau so entstand
    # "0.0000 USD (Status: gemessen)" im Receipt.
    if (ereignisse == 0)
        schreiben_unbekannt("keine usage-Ereignisse im Strom, Ausgabeformat unbekannt")
    else
        schreiben()
}
'

if [ -f "$STOPMARKER" ]; then
    claude_beenden
    exit 9
fi
exit 0
""".replace("@@PREISE@@", _PREISE_AWK).replace("@@PREISE_STAND@@", PREISE_STAND).replace(
    "@@PREIS_AUFSCHLAG@@", "%.2f" % PREIS_AUFSCHLAG
)


# ── Morning Receipt ─────────────────────────────────────────
# Laeuft im EXIT-Trap des Runners, also auch nach einem Abbruch. Felder,
# die niemand ermitteln kann, stehen als "unbekannt" drin und nicht als 0
# oder null: eine Null waere eine Aussage, die niemand geprueft hat.
RECEIPT_SH = r"""#!/bin/bash
# nightshift-receipt.sh — schreibt receipt.json und receipt.md
#
# Erwartet die Angaben in der Umgebung (setzt nightshift-run.sh):
#   NS_RUNID NS_START NS_EXIT NS_ISOLATION NS_KOSTEN NS_ZIEL
#   NS_GENRE NS_AUFGABE NS_RUNBOOK NS_STALL
set -uo pipefail

RUNID="${NS_RUNID:-unbekannt}"
START="${NS_START:-unbekannt}"
ENDE="$(date -Iseconds 2>/dev/null || date)"
EXITCODE="${NS_EXIT:-unbekannt}"
ISOLATION="${NS_ISOLATION:-unbekannt}"
KOSTEN="${NS_KOSTEN:-}"
ZIEL="${NS_ZIEL:-nightshift-receipts/$RUNID}"
GENRE="${NS_GENRE:-unbekannt}"
AUFGABE="${NS_AUFGABE:-unbekannt}"
RUNBOOK="${NS_RUNBOOK:-runbook.md}"
STALLDATEI="${NS_STALL:-}"

mkdir -p "$ZIEL" || exit 0

# ── Schritte aus dem Runbook ────────────────────────────────
# grep -c gibt bei null Treffern eine 0 aus und beendet sich mit 1. Ein
# "|| echo 0" haenge daran eine zweite Null, deshalb nur "|| true".
ERLEDIGT="unbekannt"; OFFEN="unbekannt"; GESAMT="unbekannt"; OFFENE_LISTE=""
if [ -f "$RUNBOOK" ]; then
    ERLEDIGT=$(grep -c '^- \[x\]' "$RUNBOOK" 2>/dev/null || true)
    OFFEN=$(grep -c '^- \[ \]' "$RUNBOOK" 2>/dev/null || true)
    ERLEDIGT=$(printf '%s' "${ERLEDIGT:-0}" | tr -dc '0-9')
    OFFEN=$(printf '%s' "${OFFEN:-0}" | tr -dc '0-9')
    ERLEDIGT=${ERLEDIGT:-0}; OFFEN=${OFFEN:-0}
    GESAMT=$((ERLEDIGT + OFFEN))
    OFFENE_LISTE=$(grep '^- \[ \]' "$RUNBOOK" 2>/dev/null | sed 's/^- \[ \] //' | head -20 || true)
fi

# ── Git ─────────────────────────────────────────────────────
COMMIT="unbekannt"; DATEIEN="unbekannt"; PLUS="unbekannt"; MINUS="unbekannt"
if git rev-parse --git-dir >/dev/null 2>&1; then
    COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo unbekannt)
    # Ein erfolgreiches git diff ohne Ausgabe heisst null Aenderungen und
    # nicht "unbekannt". Nur wenn beide Aufrufe scheitern, etwa weil es
    # keinen Vorgaengercommit gibt und kein Arbeitsbaum da ist, bleibt das
    # Feld unbekannt.
    KURZ=""
    if KURZ=$(git diff --shortstat HEAD~1 2>/dev/null); then
        GEMESSEN=1
    elif KURZ=$(git diff --shortstat 2>/dev/null); then
        GEMESSEN=1
    else
        GEMESSEN=0
    fi
    if [ "$GEMESSEN" = "1" ]; then
        DATEIEN=$(printf '%s' "$KURZ" | grep -oE '[0-9]+ file' | grep -oE '[0-9]+' | head -1)
        PLUS=$(printf '%s' "$KURZ" | grep -oE '[0-9]+ insertion' | grep -oE '[0-9]+' | head -1)
        MINUS=$(printf '%s' "$KURZ" | grep -oE '[0-9]+ deletion' | grep -oE '[0-9]+' | head -1)
        DATEIEN="${DATEIEN:-0}"; PLUS="${PLUS:-0}"; MINUS="${MINUS:-0}"
    fi
fi

# ── Entscheidungen ──────────────────────────────────────────
if [ -f decisions.md ]; then
    ENTSCHEIDUNGEN=$(wc -l < decisions.md | tr -d ' ')
else
    ENTSCHEIDUNGEN="unbekannt"
fi

# ── Stall-Warnungen ─────────────────────────────────────────
if [ -n "$STALLDATEI" ] && [ -f "$STALLDATEI" ]; then
    STALL=$(cat "$STALLDATEI" 2>/dev/null || echo 0)
else
    STALL="unbekannt"
fi

# ── Kosten ──────────────────────────────────────────────────
KOSTEN_STATUS="unbekannt"; TOKENS_EIN="unbekannt"; TOKENS_AUS="unbekannt"
USD="unbekannt"; BUDGET_STOP="unbekannt"
if [ -n "$KOSTEN" ] && [ -f "$KOSTEN" ] && command -v jq >/dev/null 2>&1; then
    KOSTEN_STATUS=$(jq -r '.status // "unbekannt"' "$KOSTEN" 2>/dev/null || echo unbekannt)
    TOKENS_EIN=$(jq -r '.tokens_ein // "unbekannt"' "$KOSTEN" 2>/dev/null || echo unbekannt)
    TOKENS_AUS=$(jq -r '.tokens_aus // "unbekannt"' "$KOSTEN" 2>/dev/null || echo unbekannt)
    USD=$(jq -r '.usd_geschaetzt // "unbekannt"' "$KOSTEN" 2>/dev/null || echo unbekannt)
    # Nicht "// unbekannt" nehmen: in jq ist false genauso leer wie null,
    # und ein nicht gerissenes Budget waere damit unbekannt statt false.
    BUDGET_STOP=$(jq -r 'if has("budget_ueberschritten") then .budget_ueberschritten else "unbekannt" end' "$KOSTEN" 2>/dev/null || echo unbekannt)
fi

# ── receipt.json ────────────────────────────────────────────
# Zahlenfelder nur dann als Zahl, wenn sie eine sind. Sonst der String
# "unbekannt". Kein Feld wird stillschweigend zu 0.
json_wert() {
    case "$1" in
        ''|*[!0-9.-]*) printf '"%s"' "${1:-unbekannt}" ;;
        *) printf '%s' "$1" ;;
    esac
}

# true und false gehoeren unquotiert ins JSON, alles andere ist ein String.
json_bool() {
    case "$1" in
        true|false) printf '%s' "$1" ;;
        *) printf '"%s"' "${1:-unbekannt}" ;;
    esac
}

if command -v jq >/dev/null 2>&1; then
    printf '%s\n' "$OFFENE_LISTE" | jq -R -s 'split("\n") | map(select(length > 0))' > "$ZIEL/.offen.json"
else
    printf '[]\n' > "$ZIEL/.offen.json"
fi

{
    printf '{\n'
    printf '  "run_id": "%s",\n' "$RUNID"
    printf '  "start": "%s",\n' "$START"
    printf '  "ende": "%s",\n' "$ENDE"
    printf '  "genre": "%s",\n' "$GENRE"
    printf '  "aufgabe": "%s",\n' "$AUFGABE"
    printf '  "exit_code": %s,\n' "$(json_wert "$EXITCODE")"
    printf '  "isolation": "%s",\n' "$ISOLATION"
    printf '  "schritte_gesamt": %s,\n' "$(json_wert "$GESAMT")"
    printf '  "schritte_erledigt": %s,\n' "$(json_wert "$ERLEDIGT")"
    printf '  "schritte_offen": %s,\n' "$(json_wert "$OFFEN")"
    printf '  "schritte_offen_liste": %s,\n' "$(cat "$ZIEL/.offen.json")"
    printf '  "git_commit": "%s",\n' "$COMMIT"
    printf '  "diff": { "dateien": %s, "plus": %s, "minus": %s },\n' \
        "$(json_wert "$DATEIEN")" "$(json_wert "$PLUS")" "$(json_wert "$MINUS")"
    printf '  "kosten": { "status": "%s", "tokens_ein": %s, "tokens_aus": %s, "usd_geschaetzt": %s, "budget_stop": %s },\n' \
        "$KOSTEN_STATUS" "$(json_wert "$TOKENS_EIN")" "$(json_wert "$TOKENS_AUS")" \
        "$(json_wert "$USD")" "$(json_bool "$BUDGET_STOP")"
    printf '  "entscheidungen_zeilen": %s,\n' "$(json_wert "$ENTSCHEIDUNGEN")"
    printf '  "stall_warnungen": %s\n' "$(json_wert "$STALL")"
    printf '}\n'
} > "$ZIEL/receipt.json"
rm -f "$ZIEL/.offen.json"

# ── receipt.md ──────────────────────────────────────────────
case "$EXITCODE" in
    0) AMPEL="gruen — Lauf sauber beendet" ;;
    9) AMPEL="gelb — Budget erreicht, Lauf gestoppt" ;;
    3) AMPEL="rot — ohne Isolation nicht gestartet" ;;
    *) AMPEL="rot — Lauf abgebrochen (Exit $EXITCODE)" ;;
esac

{
    printf '# Morning Receipt %s\n\n' "$RUNID"
    printf '%s\n\n' "$AMPEL"
    printf '| Angabe | Wert |\n|---|---|\n'
    printf '| Aufgabe | %s |\n' "$AUFGABE"
    printf '| Genre | %s |\n' "$GENRE"
    printf '| Start | %s |\n' "$START"
    printf '| Ende | %s |\n' "$ENDE"
    printf '| Exit-Code | %s |\n' "$EXITCODE"
    printf '| Isolation | %s |\n' "$ISOLATION"
    printf '| Schritte erledigt | %s von %s |\n' "$ERLEDIGT" "$GESAMT"
    printf '| Commit | %s |\n' "$COMMIT"
    printf '| Diff | %s Dateien, +%s / -%s |\n' "$DATEIEN" "$PLUS" "$MINUS"
    printf '| Tokens ein / aus | %s / %s |\n' "$TOKENS_EIN" "$TOKENS_AUS"
    # Ohne Messung steht hier keine Zahl. "0.0000 USD (Status: gemessen)"
    # war die Zeile, die genau das Vertrauen erzeugt hat, das sie nicht
    # tragen konnte.
    if [ "$USD" = "unbekannt" ]; then
        printf '| Kosten geschaetzt | unbekannt (Status: %s) |\n' "$KOSTEN_STATUS"
    else
        printf '| Kosten geschaetzt | %s USD (Status: %s) |\n' "$USD" "$KOSTEN_STATUS"
    fi
    printf '| Budget-Stop | %s |\n' "$BUDGET_STOP"
    printf '| Stall-Warnungen | %s |\n' "$STALL"
    printf '| decisions.md | %s Zeilen |\n' "$ENTSCHEIDUNGEN"
    printf '\n## Offene Schritte\n\n'
    if [ -n "$OFFENE_LISTE" ]; then
        printf '%s\n' "$OFFENE_LISTE" | sed 's/^/- /'
    else
        printf 'keine\n'
    fi
    printf '\n## Naechster Schritt\n\n'
    printf 'git log -1 --stat, dann runbook.md und decisions.md lesen.\n'
    printf '\n"unbekannt" heisst: dieser Lauf konnte den Wert nicht ermitteln.\n'
    printf 'Kosten bleiben unbekannt, wenn jq fehlt oder im Strom kein\n'
    printf 'einziges usage-Ereignis stand, das Ausgabeformat sich also\n'
    printf 'geaendert hat. Die Isolation ist gemessen: "docker" heisst, der\n'
    printf 'Kernel hat den Container bestaetigt, "seatbelt", dass eine Sonde\n'
    printf 'am Profil gescheitert ist, "keine", dass beides nicht zutraf.\n'
} > "$ZIEL/receipt.md"

echo "Receipt: $ZIEL/receipt.json und $ZIEL/receipt.md"
exit 0
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
