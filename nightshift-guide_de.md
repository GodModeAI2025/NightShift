# Nightshift — Trainingsanleitung

> Claude Code autonom über Nacht an deinem Projekt arbeiten lassen.

**Skill-Repository:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Landing Page:** [godmodeai2025.github.io/NightShift](https://godmodeai2025.github.io/NightShift/)

---

## Was du lernen wirst

Nach dieser Anleitung kannst du:

1. Den Nightshift-Skill in Claude Code installieren
2. Ein validiertes Runbook für jede Projektaufgabe generieren
3. Einen autonomen Overnight-Run mit Sicherheits-Hooks und Sandbox starten
4. Den Run mit dem Heartbeat-Watchdog überwachen
5. Ergebnisse prüfen und bei Bedarf zurückrollen

---

## Voraussetzungen

Stelle sicher, dass du folgendes hast:

- [ ] **Claude Code CLI** installiert und authentifiziert (tippe `claude` im Terminal)
- [ ] **bash**, **python3** (mindestens 3.9) und **jq** im PATH
- [ ] **Ein Git-Repository** mit deinem Projekt (für Rollback)
- [ ] **Docker** mit Compose v2 fuer den Standardlauf. Gilt auf Linux und macOS gleichermassen. Dazu ein `ANTHROPIC_API_KEY`, weil der Container ein eigenes Home hat.
- [ ] Optional **macOS** mit `sandbox-exec`, falls kein Docker da ist.

---

## Lektion 1: Das Problem verstehen

Öffne dein Terminal und starte Claude Code:

```bash
cd /dein/projekt
claude
```

Bitte Claude um etwas Komplexes, zum Beispiel ein Modul zu refactorn. Beobachte was passiert:

1. Claude fragt nach Erlaubnis eine Datei zu lesen → du drückst Enter
2. Claude fragt nach Erlaubnis eine Datei zu schreiben → du drückst Enter
3. Claude fragt nach Erlaubnis einen Test zu starten → du drückst Enter
4. Das Ganze 40 Mal pro Stunde

Stell dir vor, das soll über Nacht laufen. Geht nicht — Claude stoppt und wartet jedes Mal auf deine Bestätigung.

Das Flag `--dangerously-skip-permissions` entfernt alle Abfragen. Aber ohne Leitplanken hat Claude vollen Zugriff auf dein gesamtes System. Es gibt dokumentierte Fälle, in denen Home-Verzeichnisse gelöscht wurden.

**Nightshift löst das:** Es umgibt `--dangerously-skip-permissions` mit vier Schutzschichten, damit Claude sicher ohne dich arbeiten kann.

---

## Lektion 2: Skill installieren

Lade den Skill aus dem letzten Release:

```bash
mkdir -p ~/.claude/skills
curl -LO https://github.com/GodModeAI2025/NightShift/releases/latest/download/nightshift.skill
unzip nightshift.skill -d ~/.claude/skills/
```

`nightshift.skill` ist ein ZIP-Archiv. Es entpackt sich nach `~/.claude/skills/nightshift/` mit `SKILL.md`, `scripts/build_zip.py`, der Lizenz und einer `VERSION`.

Wenn der Download 404 liefert, ist noch keine Version getaggt. Dann hol die Dateien direkt aus `main`:

```bash
mkdir -p ~/.claude/skills/nightshift/scripts
curl -L https://github.com/GodModeAI2025/NightShift/raw/main/nightshift/SKILL.md -o ~/.claude/skills/nightshift/SKILL.md
curl -L https://github.com/GodModeAI2025/NightShift/raw/main/nightshift/scripts/build_zip.py -o ~/.claude/skills/nightshift/scripts/build_zip.py
```

**Prüfen:** Öffne Claude Code und tippe: "Richte einen Nightshift-Run ein für /tmp/test — erstelle eine README". Wenn Claude mit Genre-Auswahl und Runbook-Generierung antwortet, ist der Skill korrekt installiert.

---

## Lektion 3: Erstes Setup generieren

Sage Claude dein Projekt und deine Aufgabe:

```
Richte einen Nightshift-Run ein für /Users/ich/projekte/meine-api — migriere das Auth-Modul von Sessions auf JWT
```

Claude führt dich durch:

### 3.1 Genre-Auswahl

Claude erkennt den Aufgabentyp und schlägt ein Genre vor. Hier: **migration**. Bestätige oder wähle ein anderes. Jedes Genre hat vordefinierte Phasen:

| Genre | Phasen |
|-------|--------|
| migration | Kompatibilitäts-Check → Parallelbetrieb → Schrittweise Migration → Verifikation → Altsystem entfernen |
| refactoring | Ist-Analyse → Testabdeckung sichern → Umbau → Verifikation → Cleanup |
| feature | Vorbereitung → Grundstruktur → Kernlogik → Integration → Tests → Cleanup |

### 3.2 Runbook-Generierung

Claude erstellt ein Runbook mit konkreten Schritten. Prüfe es sorgfältig — **das ist, was Claude über Nacht ausführt**. Jeder Schritt braucht:

- Einen Dateipfad: `src/services/token-service.ts`
- Einen Befehl: `bun add jsonwebtoken`
- Eine konkrete Aktion: `Funktion generateAccessToken(userId: string) erstellen`

**Schlecht:** `JWT Auth implementieren` — zu vage, Claude rät.
**Gut:** `Datei src/services/token-service.ts erstellen mit Funktionen generateAccessToken(userId), verifyToken(token), refreshToken(token)`

### 3.3 Validierung

Claude validiert das Runbook gegen 15 Checks:

- Struktur: Vorbedingungen, Verifikationsphase, Rollback-Anweisung vorhanden?
- Qualität: Jeder Schritt konkret genug? Keine vagen Formulierungen?
- Sicherheit: Kein `rm -rf`? Keine hardcoded Secrets? Alle Pfade im Projekt?
- Autonomie: Drei Zonen (grün/gelb/rot) definiert? Fehler-Budget mit Stop-Bedingung?

Bei Fehlern schlägt Claude Fixes vor. Der Generator schreibt die ZIP trotzdem. Ein fehlgeschlagener Check stoppt nichts, er ist ein Hinweis, das Runbook nachzubessern.

### 3.4 Setup-Dateien

Claude erzeugt diese Dateien:

| Datei | Funktion |
|-------|----------|
| `runbook.md` | Aufgabenplan — Claudes externes Gedächtnis |
| `.claude/settings.json` | Sicherheits-Hooks, Heartbeat, Compact-Recovery, Checkpoint |
| `nightshift-run.sh` | Das Hauptskript |
| `nightshift-watchdog.sh` | Heartbeat-Monitor |
| `nightshift-sandbox.sb` | macOS Kernel-Sandbox-Profil |

---

## Lektion 4: Installieren und starten

### 4.1 Dateien kopieren

```bash
cd /dein/projekt
cp nightshift-setup/runbook.md .
cp nightshift-setup/nightshift-*.sh .
cp nightshift-setup/nightshift-sandbox.sb .
cat nightshift-setup/CLAUDE-nightshift.md >> CLAUDE.md
chmod +x nightshift-*.sh

# Hook-Konfiguration. Eine vorhandene settings.json wird nicht ueberschrieben.
if [ -e .claude/settings.json ]; then
  echo "STOPP: .claude/settings.json existiert, zusammenfuehren statt kopieren (siehe unten)"
else
  mkdir -p .claude
  cp -R nightshift-setup/.claude/. .claude/
fi

# Ohne diese Datei laeuft der Lauf ohne Hooks und ohne Schutzschicht
test -f .claude/settings.json && echo "Hooks aktiv" || echo "WARNUNG: keine Hooks"
```

**Wenn `.claude/settings.json` schon existiert:** zusammenfuehren statt kopieren.
Der Befehl behaelt deine eigenen Hooks, Permissions und MCP-Einstellungen und
haengt die Nightshift-Hooks je Ereignistyp an:

```bash
jq -s '(.[0].hooks // {}) as $mine | (.[1].hooks // {}) as $new
       | (.[0] * .[1])
       | .hooks = (reduce (($mine | to_entries[]), ($new | to_entries[])) as $e
                   ({}; .[$e.key] = ((.[$e.key] // []) + $e.value)))' \
  .claude/settings.json nightshift-setup/.claude/settings.json \
  > .claude/settings.merged.json

# durchlesen, dann uebernehmen
mv .claude/settings.merged.json .claude/settings.json
```

### 4.2 Vorher committen (Pflicht!)

```bash
git add -A && git commit -m "Stand vor Nightshift"
```

Das ist dein Undo-Button. Ohne diesen Commit gibt es kein Zurück.

### 4.3 Starten

**Im Container (Standardweg):**
```bash
export ANTHROPIC_API_KEY=sk-ant-...
./nightshift-docker.sh
```
Baut beide Images, mountet nur das Projekt nach `/project`, laesst die Nacht laufen und raeumt danach auf. Budget: 25 USD, per `NIGHTSHIFT_BUDGET_USD=5 ./nightshift-docker.sh` fuer einen Lauf anders.

**Mit Seatbelt-Profil (macOS-Option):**
```bash
sandbox-exec -f nightshift-sandbox.sb ./nightshift-run.sh
```

Keine Umgebungsvariable im Spiel: der Runner prueft mit einer Sonde, ob er wirklich hinter dem Profil sitzt. Unter dem Profil kann er das Projekt auflisten, `/Users` aber nicht, und genau das ergibt den Zustand `seatbelt`.

Ein blosses `./nightshift-run.sh` bricht mit Exit-Code 3 ab. Wer bewusst ohne Isolation laufen will, setzt `NIGHTSHIFT_ALLOW_UNSANDBOXED=1`; im Receipt steht dann `keine`. `NIGHTSHIFT_SANDBOXED` ist nur noch die Gegenprobe: widerspricht der Wert der Messung, bricht der Lauf mit 3 ab. Frueher genuegte ein beliebiges Wort in dieser Variablen, um den Lauf durchzulassen.

**Im Hintergrund (Terminal kann geschlossen werden):**
```bash
./nightshift-run-bg.sh
```

**Was jetzt passiert:**
1. Claude startet im Headless-Modus (`claude -p`)
2. Liest `runbook.md` für den Aufgabenplan
3. Arbeitet Schritte ab, hakt erledigte ab
4. Jeder Tool-Call triggert einen Heartbeat
5. Nach Kontextkomprimierung sagt der Hook: "Lies runbook.md erneut"
6. Alle 5 erledigte Schritte werden Autonomiebereiche und Fehler-Budget wiederholt
7. Am Ende committed Claude die Änderungen

### 4.4 Überwachen (optional)

Im zweiten Terminal:

```bash
./nightshift-watchdog.sh          # Alarm nach 10 Min ohne Heartbeat
./nightshift-watchdog.sh 300      # Alarm nach 5 Min
```

---

## Lektion 5: Ergebnisse prüfen

Am nächsten Morgen:

```bash
# Was hat Claude committed?
git log --oneline -5

# Was hat sich geändert?
git diff HEAD~1

# Welche Schritte wurden erledigt?
cat runbook.md | grep "\[x\]"

# Welche Schritte fehlen?
cat runbook.md | grep "\[ \]"
```

### Wenn etwas schiefging

```bash
# Alles rückgängig machen
git checkout .

# Oder Änderungen sichern
git stash

# Prozess beenden falls noch aktiv
pkill -f "claude.*dangerously"
```

---

## Lektion 6: Worauf du achten musst

### API-Kosten
Jeder Headless-Run verbraucht API-Credits. Nightshift zaehlt sie mit: `nightshift-cost.sh` summiert die usage-Felder aus der stream-json-Ausgabe, schaetzt die Dollar aus einer datierten Preistabelle und beendet am Budget die Prozessgruppe von Claude mit Exit-Code 9. Gegen einen echten Lauf gemessen lag die Schaetzung bei 0.25860 USD, Claude selbst meldete 0.25863 USD fuer dieselbe Anfrage. Ein Modell, das die Tabelle nicht kennt, wird mit dem Doppelten der teuersten bekannten Zeile gerechnet: ein neueres Modell kann teurer sein als alles in der Tabelle. Steht im Strom kein einziges usage-Ereignis, etwa weil sich das Ausgabeformat geaendert hat, schreibt der Zaehler `unbekannt` und keine Null. Die Zahl im Receipt bleibt eine Schaetzung, die Rechnung steht unter console.anthropic.com.

### Der Lauf ohne Isolation bricht ab
`nightshift-run.sh` prueft vor dem Claude-Aufruf, wie es eingesperrt ist: Container, Seatbelt oder nichts. Bei nichts endet der Lauf mit Exit-Code 3. `NIGHTSHIFT_ALLOW_UNSANDBOXED=1` ist der bewusste Weg daran vorbei.

### Der Morning Receipt
Nach jedem Lauf liegen `nightshift-receipts/<lauf>/receipt.json` und `receipt.md` im Projekt, auch nach einem Abbruch. Was der Lauf nicht ermitteln konnte, steht dort als `unbekannt` und nicht als 0.

### Runbook-Qualität = Ergebnis-Qualität
Vage Schritte erzeugen vage Ergebnisse. Prüfe das Runbook vor dem Start. Bei mehr als 20 Schritten auf mehrere Runs aufteilen.

### Kontextkomprimierung
Bei Runs über 20 Minuten passiert Kontextkomprimierung. Die Hooks fangen das ab, aber bei 30+ Schritten sinkt die Qualität. Unter 20 Schritte pro Run bleiben.

### Linux-Nutzer
`sandbox-exec` gibt es nur auf macOS, und gebraucht wird es nicht mehr: `./nightshift-docker.sh` ist auf beiden Systemen derselbe Weg und die schaerfere Grenze, weil auch Lesezugriffe und der Netzverkehr eingeschraenkt sind.

Ohne Docker bleibt ein eigener Benutzer als schwaechere Notloesung:
```bash
sudo useradd -m clauderunner
sudo cp -r /dein/projekt /home/clauderunner/projekt
sudo chown -R clauderunner: /home/clauderunner/projekt
sudo -u clauderunner env NIGHTSHIFT_PROJEKT=/home/clauderunner/projekt \
    NIGHTSHIFT_ALLOW_UNSANDBOXED=1 \
    bash /home/clauderunner/projekt/nightshift-run.sh
```
Die Kopie aus `sudo cp -r` gehoert sonst root, und der Runner kann in seinem eigenen Arbeitsverzeichnis nicht schreiben. `NIGHTSHIFT_PROJEKT` schiebt den Lauf in die Kopie, sonst arbeitet er im Originalverzeichnis weiter. Das neue Konto braucht eine eigene Claude-Code-Anmeldung. Das Konto erreicht weiterhin das Netz und liest alles, was fuer alle lesbar ist, deshalb der ausdrueckliche Opt-out.

---

## Übungsaufgabe

Probiere es mit einem Testprojekt:

1. Kleines Node.js-Projekt erstellen: `mkdir /tmp/nightshift-test && cd /tmp/nightshift-test && npm init -y && git init && git add -A && git commit -m "init"`
2. Nightshift-Skill installieren
3. Claude sagen: "Richte einen Nightshift-Run ein für /tmp/nightshift-test — erstelle eine ausführliche README mit Installation, Usage und API-Doku basierend auf package.json"
4. Generiertes Runbook prüfen
5. Starten (Vordergrund, ohne Sandbox da Testprojekt)
6. Ergebnis prüfen

---

**Quellcode:** [github.com/GodModeAI2025/NightShift](https://github.com/GodModeAI2025/NightShift)
**Impressum:** [godmodeai2025.github.io/MarkZimmermann](https://godmodeai2025.github.io/MarkZimmermann/)
