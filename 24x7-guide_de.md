# 24x7 — Trainingsanleitung

> Ein endloser Claude Code Runner mit Inbox/Outbox-Aufgabenwarteschlange.

**Skill-Repository:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Landing Page:** [godmodeai2025.github.io/NightShift](https://godmodeai2025.github.io/NightShift/)

---

## Was du lernen wirst

Nach dieser Anleitung kannst du:

1. Den 24x7-Skill in Claude Code installieren
2. Einen endlosen Runner mit Inbox/Outbox-Architektur einrichten
3. Aufgaben als Ordner einwerfen und Ergebnisse abholen
4. Idle-Verhalten konfigurieren wenn die Warteschlange leer ist
5. Den Runner überwachen und Fehler behandeln

---

## Voraussetzungen

- [ ] **Claude Code CLI** installiert und authentifiziert
- [ ] **bash**, **python3** (mindestens 3.9) und **jq** im PATH
- [ ] **timeout** oder **gtimeout** im PATH. macOS bringt `timeout` nicht mit: `brew install coreutils` liefert `gtimeout`. Ohne eins von beiden startet der Runner nicht.
- [ ] **macOS** empfohlen (für Sandbox). Linux funktioniert ohne.
- [ ] Ein Verzeichnis für den Workspace (kein Git nötig, anders als bei Nightshift)

---

## Lektion 1: Nightshift vs. 24x7 — Wann welchen Skill?

**Nightshift** ist ein Sprint: Ein Projekt, eine Aufgabe, ein Run, ein Commit. Nimm es wenn du eine geplante, konkrete Arbeit hast.

**24x7** ist ein Daemon: Eine Endlosschleife, die Aufgaben aus einer Warteschlange abarbeitet. Nimm es wenn:

- Du mehrere kleine Aufgaben über den Tag verteilt hast
- Du Arbeit einwerfen und später Ergebnisse abholen willst
- Du einen dauerhaft bereiten Worker brauchst
- Aufgaben voneinander unabhängig sind

Der entscheidende Architekturuntersched: **Nightshift nutzt eine lange Claude-Session** mit Compact-Recovery-Hooks. **24x7 nutzt eine frische Session pro Task** — kein Context Rot, keine Compact-Probleme, jeder Task bekommt Claude in voller Qualität.

---

## Lektion 2: Skill installieren

```bash
mkdir -p ~/.claude/skills
curl -LO https://github.com/GodModeAI2025/NightShift/releases/latest/download/24x7.skill
unzip 24x7.skill -d ~/.claude/skills/
```

`24x7.skill` ist ein ZIP-Archiv. Es entpackt sich nach `~/.claude/skills/24x7/` mit `SKILL.md`, `scripts/build_zip.py`, der Lizenz und einer `VERSION`.

Wenn der Download 404 liefert, ist noch keine Version getaggt. Dann hol die Dateien direkt aus `main`:

```bash
mkdir -p ~/.claude/skills/24x7/scripts

curl -L https://github.com/GodModeAI2025/NightShift/raw/main/24x7/SKILL.md -o ~/.claude/skills/24x7/SKILL.md
curl -L https://github.com/GodModeAI2025/NightShift/raw/main/24x7/scripts/build_zip.py -o ~/.claude/skills/24x7/scripts/build_zip.py
```

**Prüfen:** Sage Claude: "Richte einen 24x7 Runner ein unter /tmp/test-workspace". Wenn Claude mit Workspace-Setup und Idle-Auswahl antwortet, ist der Skill installiert.

---

## Lektion 3: Workspace generieren

Sage Claude:

```
Richte einen 24x7 Runner ein unter /Users/ich/claude-workspace mit Idle-Verhalten cleanup
```

Claude fragt nach:
1. **Workspace-Pfad** — wo der Runner leben soll
2. **Idle-Verhalten** — was Claude tut wenn die Inbox leer ist

### Idle-Optionen

| Option | Was passiert | API-Kosten |
|--------|-------------|------------|
| cleanup | Workspace aufräumen, TODOs aus erledigten Tasks sammeln | Niedrig |
| docs | Workspace-README mit Task-Zusammenfassungen aktualisieren | Niedrig |
| tests | Tests vorschlagen für Code in erledigten Tasks | Mittel |
| sleep | Nichts tun, warten | Null |

Wähle `sleep` wenn API-Kosten ein Thema sind. Der Runner pollt dann die Inbox alle 30 Sekunden ohne Claude aufzurufen.

---

## Lektion 4: Ordnerstruktur verstehen

```
workspace/
├── inbox/           ← DU legst Task-Ordner hier rein
│   └── mein-task/
│       ├── task.md      ← Der Auftrag (Pflicht)
│       └── materials/   ← Eingabedateien (optional)
│
├── working/         ← RUNNER verschiebt Tasks hierhin während Bearbeitung
│
├── outbox/          ← RUNNER legt erledigte Tasks hier ab
│   └── mein-task/
│       ├── task.md      ← Original-Auftrag
│       ├── materials/   ← Original-Input
│       ├── output/      ← ERGEBNISSE — das willst du
│       └── log.md       ← Was Claude gemacht hat
│
├── failed/          ← RUNNER legt fehlgeschlagene Tasks hier ab
│
└── idle/
    └── idle-tasks.md
```

**Der Ablauf:**
1. Du erstellst einen Ordner in `inbox/` mit einer `task.md`
2. Runner erkennt ihn, verschiebt ihn nach `working/`
3. Claude bearbeitet ihn in einer frischen Session
4. Erfolg → `outbox/`. Fehler → `failed/`
5. Runner prüft die Inbox erneut

---

## Lektion 5: Eine task.md schreiben

Jeder Task braucht eine `task.md`. Das Format:

```markdown
## Task: [Titel]
Priorität: [hoch/mittel/niedrig]

### Auftrag
[Was genau zu tun ist — sei konkret]

### Input
[Welche Dateien in materials/ relevant sind]

### Erwarteter Output
[Was in output/ erscheinen soll — Dateinamen, Formate]
```

### Beispiel: Code-Generierung

```markdown
## Task: REST API Client erstellen
Priorität: hoch

### Auftrag
Erstelle einen TypeScript REST API Client für die JSONPlaceholder API.
CRUD-Methoden für /posts und /users.
Fehlerbehandlung und TypeScript-Interfaces für alle Response-Typen.

### Input
- materials/api-spec.md — API-Endpunkt-Dokumentation

### Erwarteter Output
- output/api-client.ts — Die Client-Klasse
- output/types.ts — TypeScript Interfaces
- output/api-client.test.ts — Unit Tests
```

### Beispiel: Recherche-Aufgabe

```markdown
## Task: Edge-Computing-Frameworks vergleichen
Priorität: niedrig

### Auftrag
Recherchiere aktuelle Edge-Computing-Frameworks für IoT-Sensordaten.
Vergleiche mindestens 4 Frameworks: Kosten, Latenz, Offline-Fähigkeit, Sprachsupport.

### Input
- materials/anforderungen.md — Unsere technischen Anforderungen

### Erwarteter Output
- output/vergleich.md — Tabellarischer Vergleich
- output/empfehlung.md — Begründete Empfehlung mit Vor-/Nachteilen
```

### Qualitätsregeln

Gute Tasks sind **konkret, abgegrenzt und überprüfbar**:

- Dateinamen für erwarteten Output angeben
- Konkrete Akzeptanzkriterien formulieren
- Alle nötigen Eingabedaten in `materials/` bereitstellen
- Umfang auf das beschränken, was Claude in unter 60 Minuten schaffen kann

Schlechte Tasks sind vage: "Verbessere die Codebase" oder "Fix alles". Claude rät, und niemand korrigiert.

---

## Lektion 6: Starten und überwachen

### Dateien in den Workspace kopieren

```bash
cd /dein/workspace

# Das Glob * erfasst keine Dotfiles, .claude braucht einen eigenen Schritt
cp -r /pfad/zu/24x7-setup/* .

# Hook-Konfiguration. Eine vorhandene settings.json wird nicht ueberschrieben.
if [ -e .claude/settings.json ]; then
  echo "STOPP: .claude/settings.json existiert, zusammenfuehren statt kopieren (siehe unten)"
else
  mkdir -p .claude
  cp -R /pfad/zu/24x7-setup/.claude/. .claude/
fi

# Ohne diese Datei laeuft der Runner voellig ohne Hooks
test -f .claude/settings.json && echo "Hooks aktiv" || echo "WARNUNG: keine Hooks"
```

**Wenn `.claude/settings.json` schon existiert:** zusammenfuehren statt kopieren.
Der Befehl behaelt deine eigenen Eintraege und haengt die 24x7-Hooks je
Ereignistyp an:

```bash
jq -s '(.[0].hooks // {}) as $mine | (.[1].hooks // {}) as $new
       | (.[0] * .[1])
       | .hooks = (reduce (($mine | to_entries[]), ($new | to_entries[])) as $e
                   ({}; .[$e.key] = ((.[$e.key] // []) + $e.value)))' \
  .claude/settings.json /pfad/zu/24x7-setup/.claude/settings.json \
  > .claude/settings.merged.json

# durchlesen, dann uebernehmen
mv .claude/settings.merged.json .claude/settings.json
```

### Runner starten

```bash
cd /dein/workspace
chmod +x *.sh
./runner-bg.sh
```

### Watchdog starten

```bash
./watchdog.sh

# Nicht nur melden, sondern reagieren:
CLAUDE_24X7_WATCHDOG_AKTION=neustart ./watchdog.sh
```

`beenden` schickt dem Runner TERM und nach 20 Sekunden KILL, `neustart` startet ihn danach wieder, standardmaessig einmal. Der laufende Task landet dabei in `failed/`, dafuer sorgt der Trap im Runner. Neu gestartet wird nur ein Runner, den der Watchdog selbst beendet hat.

Zeigt alle 60 Sekunden den Status:
```
✅ 14:32:01: OK (12s) | 📥3 🔄1 ✅8 ❌0
```

### Task einwerfen (jederzeit)

```bash
mkdir -p inbox/neuer-task/materials
cp meine-dateien.* inbox/neuer-task/materials/
nano inbox/neuer-task/task.md
# Runner erkennt den Task innerhalb von 30 Sekunden
```

### Ergebnisse abholen

```bash
ls outbox/neuer-task/output/
cat outbox/neuer-task/log.md
```

### Runner stoppen

```bash
kill $(cat /tmp/24x7.pid)
```

Der Runner beendet sich sauber: laufender Task wird nach `failed/` verschoben, PID-Datei aufgeräumt.

---

## Lektion 7: Fehler behandeln

Tasks in `failed/` haben eine `log.md` mit Fehlerinfos:

| Fehler | log.md sagt | Lösung |
|--------|------------|--------|
| Timeout (60 Min) | `TIMEOUT` | Task vereinfachen oder MAX_SECONDS in runner.sh erhöhen |
| Claude-Fehler | `EXIT CODE: 1` | task.md präziser formulieren, materials prüfen |
| Runner gestoppt | `ABBRUCH: Runner wurde beendet` | Task war in Bearbeitung. Zurück in Inbox: `mv failed/mein-task inbox/` |

### Task erneut versuchen

```bash
mv failed/mein-task inbox/mein-task
```

---

## Lektion 8: Worauf du achten musst

### API-Kosten — Das größte Risiko
24x7 erzeugt **kontinuierlich** API-Calls. Auch Idle-Tasks kosten Geld. Ein Runner mit 10 Tasks pro Tag kostet $20–100/Tag. Setze Idle auf `sleep` um Kosten bei leerer Inbox zu vermeiden. Überwache unter console.anthropic.com.

### Der Runner startet nicht ohne Isolation
Standardweg ist der Container: `./24x7-docker.sh`. Er baut das Image und startet den Runner darin, der Workspace haengt unter `/workspace`, Tasks wirfst du weiter auf dem Host in `inbox/`. Ohne Container und ohne Seatbelt-Profil bricht `runner.sh` mit Exit 3 ab; bewusst ohne Isolation laufen laesst du ihn mit `CLAUDE_24X7_ALLOW_UNSANDBOXED=1`.

Die macOS-Option bleibt `sandbox-exec -f sandbox.sb ./runner.sh`. Sie deckelt das Schreiben, nicht das Lesen und nicht den Netzverkehr. Der Watchdog laeuft nur beim Lauf auf dem Host mit: im Container liegt der Heartbeat in einem eigenen tmpfs, dort liest du stattdessen `docker compose logs -f 24x7`.

Eine Haelfte greift auch ohne Profil: Der PreToolUse-Hook prueft den Zielpfad von Write, Edit, MultiEdit und NotebookEdit und beendet den Aufruf mit Exit 2, wenn er aus dem Workspace hinauszeigt. Ein Schreibvorgang, den ein Bash-Kommando ausfuehrt, und jedes Lesen bleiben davon unberuehrt.

### Tasks sind sequentiell
Der Runner bearbeitet einen Task gleichzeitig. Für parallele Verarbeitung: mehrere Runner in getrennten Workspaces starten.

### Kein geteilter Zustand zwischen Tasks
Jeder Task bekommt eine frische Claude-Session. Claude erinnert sich nicht an den vorherigen Task. Wenn Tasks voneinander abhängen, den Kontext in `materials/` mitliefern.

### Task-Timeout
Standard: 60 Minuten. Tasks die länger dauern werden beendet und nach `failed/` verschoben. `MAX_SECONDS` in `runner.sh` anpassen falls nötig.

---

## Lektion 9: Konfiguration

In `runner.sh` anpassen:

| Variable | Standard | Funktion |
|----------|----------|----------|
| `POLL` | 30 | Sekunden zwischen Inbox-Checks |
| `MAX_SECONDS` | 3600 | Timeout pro Task (60 Min) |
| `IDLE_SECONDS` | 900 | Timeout für Idle-Tasks (15 Min) |

`idle/idle-tasks.md` bearbeiten um das Idle-Verhalten zu ändern.

---

## Übungsaufgabe

1. Workspace erstellen: `mkdir -p /tmp/24x7-test`
2. 24x7-Skill installieren
3. Claude sagen: "Richte einen 24x7 Runner ein unter /tmp/24x7-test mit Idle-Verhalten sleep"
4. Dateien kopieren und Runner starten
5. Drei Tasks einwerfen:
   - `inbox/task-1/task.md` — "Schreibe ein Haiku über Programmieren. Output: output/haiku.md"
   - `inbox/task-2/task.md` — "Liste die ersten 20 Primzahlen. Output: output/primzahlen.md"
   - `inbox/task-3/task.md` — "Schreibe einen Bash-Einzeiler der Dateien im aktuellen Verzeichnis zählt. Output: output/einzeiler.md"
6. Watchdog beobachten während Tasks verarbeitet werden
7. Ergebnisse aus `outbox/` abholen

---

**Quellcode:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Impressum:** [godmodeai2025.github.io/MarkZimmermann](https://godmodeai2025.github.io/MarkZimmermann/)
