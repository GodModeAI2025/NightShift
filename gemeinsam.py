#!/usr/bin/env python3
"""Gemeinsame Bausteine beider Generatoren.

Die Schutzschicht stand zweimal im Repo: dasselbe grep-Muster, derselbe
Hook-Rumpf, einmal in nightshift/scripts/build_zip.py und einmal in
24x7/scripts/build_zip.py. Wer nur eine Kopie anfasste, verschob den Schutz
fuer einen der beiden Skills. Seit Welle 7 steht der Teil hier, und beide
Generatoren lesen ihn.

Zwei Orte, an denen diese Datei liegen kann, und beide muessen funktionieren:

    im Repo         gemeinsam.py neben README.md
    installiert     ~/.claude/skills/<skill>/scripts/gemeinsam.py

Deshalb sucht build_zip.py sie erst neben sich und dann zwei Ebenen darueber.
scripts/build_release.py legt sie in beide Artefakte, sonst laeuft der Skill
nach dem Entpacken nicht.

Nur Standardbibliothek, und alles muss unter Python 3.9 laufen: das ist das
System-Python von macOS und die dokumentierte Untergrenze.
"""

# ── Kommandomuster der roten Zone ───────────────────────────
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

# Der Matcher der Pfadschranke. Claude Code vergleicht ihn als regulaeren
# Ausdruck gegen den Werkzeugnamen. MultiEdit steht mit drin, weil aeltere
# Claude-Code-Versionen Mehrfachaenderungen unter diesem Namen fuehren.
PFAD_MATCHER = "Write|Edit|MultiEdit|NotebookEdit"

# jq-Programm der Pfadschranke. Es bekommt die Hook-Eingabe auf stdin und
# $home als Argument und gibt genau eine Zeile aus: den normalisierten
# absoluten Zielpfad, oder eine leere Zeile, wenn kein Ziel bestimmbar ist.
#
# Normalisiert wird rein lexikalisch: "." faellt weg, ".." nimmt ein Segment
# zurueck, doppelte Schraegstriche verschwinden, "~/" wird zu $HOME. Symlinks
# werden nicht aufgeloest; dafuer muesste der Hook das Dateisystem befragen,
# und das Ziel eines Write existiert in der Regel noch gar nicht.
#
# Keine einfachen Anfuehrungszeichen in diesem Text: er wird unten in
# einfache Anfuehrungszeichen gepackt.
_PFAD_JQ = (
    'def norm: split("/") | reduce .[] as $s ([]; '
    'if $s == "" or $s == "." then . '
    'elif $s == ".." then .[0:-1] '
    'else . + [$s] end) | "/" + join("/"); '
    '(.cwd // "") as $wd | '
    "(.tool_input.file_path // .tool_input.notebook_path // "
    '.tool_input.path // "") as $p | '
    'if $p == "" then "" '
    'elif ($p | startswith("~/")) then ($home + $p[1:] | norm) '
    'elif ($p | startswith("/")) then ($p | norm) '
    'elif $wd == "" then "" '
    'else ($wd + "/" + $p | norm) end'
)

# Rumpf der Kommandoschranke. @@MARKE@@ wird durch den Namen des Skills
# ersetzt, @@MUSTER@@ durch BLOCK_PATTERN.
_KOMMANDO_SKRIPT = (
    "if ! command -v jq >/dev/null 2>&1; then "
    'echo "@@MARKE@@ BLOCKED: jq nicht gefunden, Kommando nicht pruefbar" >&2; '
    "exit 2; "
    "fi; "
    "INPUT=$(cat); "
    'CMD=$(printf "%s" "$INPUT" | jq -r ".tool_input.command // empty") || '
    '{ echo "@@MARKE@@ BLOCKED: jq konnte die Eingabe nicht lesen" >&2; exit 2; }; '
    'if [ -n "$CMD" ] && printf "%s" "$CMD" | tr -d "\\047\\042" | grep -qE '
    "'@@MUSTER@@'; then "
    'echo "@@MARKE@@ BLOCKED: Destruktiver Befehl" >&2; exit 2; '
    "fi; "
    "exit 0"
)

# Rumpf der Pfadschranke. Zusaetzlich zu @@MARKE@@ werden @@VARIABLE@@ und
# @@STANDARD@@ ersetzt: die Umgebungsvariable, aus der die erlaubte Wurzel
# kommt, und der Pfad, der gilt, wenn sie nicht gesetzt ist.
_PFAD_SKRIPT = (
    "if ! command -v jq >/dev/null 2>&1; then "
    'echo "@@MARKE@@ BLOCKED: jq nicht gefunden, Zielpfad nicht pruefbar" >&2; '
    "exit 2; "
    "fi; "
    'WURZEL="${@@VARIABLE@@:-@@STANDARD@@}"; '
    'case "$WURZEL" in /) ;; */) WURZEL="${WURZEL%/}" ;; esac; '
    "INPUT=$(cat); "
    'ZIEL=$(printf "%s" "$INPUT" | jq -r --arg home "$HOME" '
    "'@@JQ@@') || "
    '{ echo "@@MARKE@@ BLOCKED: jq konnte die Eingabe nicht lesen" >&2; exit 2; }; '
    'if [ -z "$ZIEL" ]; then '
    'echo "@@MARKE@@ BLOCKED: kein Zielpfad in der Eingabe, nicht pruefbar" >&2; '
    "exit 2; "
    "fi; "
    'case "$ZIEL" in '
    '"$WURZEL"/.claude/settings.json|"$WURZEL"/.claude/settings.local.json) '
    'echo "@@MARKE@@ BLOCKED: Hook-Konfiguration ist fuer den Lauf tabu: $ZIEL" >&2; '
    "exit 2 ;; "
    '"$WURZEL"|"$WURZEL"/*) exit 0 ;; '
    "esac; "
    'echo "@@MARKE@@ BLOCKED: Schreibziel ausserhalb von $WURZEL: $ZIEL" >&2; '
    "exit 2"
)


def bash_hook(skript):
    """Packt ein Shellskript so, dass es als Hook-Kommando dasteht.

    Claude Code startet Hooks ueber die Shell. Der Rumpf steht deshalb in
    einfachen Anfuehrungszeichen, und jedes einfache Anfuehrungszeichen darin
    wird nach der ueblichen Regel maskiert.
    """
    return "bash -c '" + skript.replace("'", "'\\''") + "'"


def kommando_schranke(marke):
    """Hook, der vor jedem Bash-Aufruf den Kommandotext prueft.

    Ohne jq kann der Hook nichts pruefen. Dann blockt er und sagt warum,
    statt still durchzuwinken (fail closed).
    """
    skript = _KOMMANDO_SKRIPT.replace("@@MUSTER@@", BLOCK_PATTERN)
    return bash_hook(skript.replace("@@MARKE@@", marke))


def pfad_schranke(marke, wurzel_variable, wurzel_standard):
    """Hook, der vor Write, Edit und NotebookEdit den Zielpfad prueft.

    Der Kommando-Hook sieht nur Bash. Write, Edit und NotebookEdit erreichen
    ihn nie, und ein Kommandotext ist ohnehin der falsche Gegenstand fuer die
    Frage nach dem Ziel. Dieser Hook prueft deshalb den Pfad:

      * ausserhalb der Wurzel  -> Exit 2, der Schreibvorgang faellt aus
      * innerhalb der Wurzel   -> Exit 0, der Lauf arbeitet weiter
      * kein Pfad bestimmbar   -> Exit 2, denn jedes der vier Werkzeuge
                                  bringt einen mit; fehlt er, ist die
                                  Eingabe kaputt und nicht pruefbar
      * Hook-Konfiguration     -> Exit 2, auch innerhalb der Wurzel. Ein Lauf,
                                  der seine eigene Schranke umschreiben darf,
                                  hat keine.

    Die Wurzel kommt zur Laufzeit aus wurzel_variable, damit derselbe Hook im
    Container greift, wo das Projekt an einer anderen Stelle haengt als beim
    Generieren. Setzt der Betreiber die Variable weit, ist die Schranke weit;
    aus einem Bash-Aufruf heraus laesst sie sich nicht aendern, denn Hooks
    erben die Umgebung des Claude-Prozesses.
    """
    skript = _PFAD_SKRIPT.replace("@@JQ@@", _PFAD_JQ)
    skript = skript.replace("@@VARIABLE@@", wurzel_variable)
    skript = skript.replace("@@STANDARD@@", wurzel_standard)
    return bash_hook(skript.replace("@@MARKE@@", marke))


def pretooluse(marke, wurzel_variable, wurzel_standard):
    """Beide PreToolUse-Eintraege: erst der Kommandotext, dann der Zielpfad."""
    return [
        {
            "matcher": "Bash",
            "hooks": [{"type": "command", "command": kommando_schranke(marke)}],
        },
        {
            "matcher": PFAD_MATCHER,
            "hooks": [
                {
                    "type": "command",
                    "command": pfad_schranke(
                        marke, wurzel_variable, wurzel_standard
                    ),
                }
            ],
        },
    ]


# ════════════════════════════════════════════════════════════
#  Container: dasselbe Gehaeuse fuer beide Skills
# ════════════════════════════════════════════════════════════
# Bis Welle 6 gab es den Container nur fuer Nightshift, und damit lief die
# Haelfte des Produkts ungeschuetzt. Statt die Dateien zu verdoppeln, stehen
# sie hier einmal mit Platzhaltern. Was sich zwischen den Skills wirklich
# unterscheidet, ist die Wortliste unten, nicht die Haertung.

_DOCKERFILE = r"""# syntax=docker/dockerfile:1
# @@TITEL@@-Container. Zwei Ziele, ein File:
#   runner  laeuft Claude Code, sieht nur @@MOUNT@@ und kein offenes Netz
#   egress  Proxy mit Allowlist, der einzige Weg nach draussen
#
# Bauen und starten uebernimmt ./@@DOCKERSKRIPT@@.

# ─────────────────────────── runner ───────────────────────────
FROM node:22-bookworm-slim AS runner

# git fuer die Commits, jq fuer Hook und Kostenzaehler, procps fuers
# Nachsehen, was noch laeuft, ca-certificates fuer TLS durch den Proxy.
@@WERKZEUGNOTIZ@@
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl git jq procps \
 && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

# @@SANDBOXVAR@@ ist hier nur die Gegenprobe: der Runner misst
# selbst am Kernel, ob er im Container sitzt, und bricht ab, wenn die
# Variable etwas anderes behauptet. @@PFADVAR@@ haelt den Pfad im
# Container beweglich: @@GEGENSTAND@@ liegt hier unter @@MOUNT@@, nicht unter
# dem Pfad, der beim Generieren gesetzt war.
ENV @@SANDBOXVAR@@=docker \
    @@PFADVAR@@=@@MOUNT@@ \
    HOME=/home/node \
    CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1

WORKDIR @@MOUNT@@
USER node
CMD ["bash", "@@MOUNT@@/@@STARTSKRIPT@@"]

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
"""

_COMPOSE = """# @@KOPF@@
#
#   ./@@DOCKERSKRIPT@@
#
# Was der Container sieht: @@HOSTPFAD@@ unter @@MOUNT@@, sonst nichts vom
# Host. Kein Home, kein ~/.claude, keine Nachbarprojekte. Nach draussen
# kommt er nur ueber den Proxy und nur zu den Hosts in dessen Allowlist.

services:
  @@DIENST@@:
    build:
      context: .
      target: runner
    image: @@DIENST@@-runner
    init: true
    working_dir: @@MOUNT@@
    command: ["bash", "@@MOUNT@@/@@STARTSKRIPT@@"]
    volumes:
      # Der einzige Pfad vom Host. Schreibbar, weil Claude hier arbeitet.
      - "@@HOSTPFAD@@:@@MOUNT@@"
      # Eigenes Home im Volume, damit ~/.claude des Hosts aussen bleibt.
      - "@@DIENST@@-home:/home/node"
    environment:
      # Ohne Schluessel bricht der Runner mit einer Meldung ab. Der
      # Schluessel wird nicht ins Image gebacken, er kommt aus der Umgebung
      # oder aus einer .env neben dieser Datei.
      ANTHROPIC_API_KEY: "${ANTHROPIC_API_KEY:-}"
      HTTPS_PROXY: "http://egress:8888"
      HTTP_PROXY: "http://egress:8888"
      NO_PROXY: "localhost,127.0.0.1"
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1"@@ZUSATZENV@@
    depends_on:
      - egress
    networks:
      - @@DIENST@@-intern
    # Alles ausser @@MOUNT@@, /home/node und /tmp ist unveraenderlich.
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - "no-new-privileges:true"
    pids_limit: 512
    mem_limit: @@SPEICHER@@

  egress:
    build:
      context: .
      target: egress
    image: @@DIENST@@-egress
    init: true
    networks:
      # Haengt in beiden Netzen und ist damit die einzige Bruecke nach
      # draussen. Was nicht in der Allowlist steht, beantwortet der Proxy
      # mit 403.
      - @@DIENST@@-intern
      - @@DIENST@@-extern
    read_only: true
    tmpfs:
      - /tmp
    cap_drop:
      - ALL
    security_opt:
      - "no-new-privileges:true"
    mem_limit: 256m

networks:
  @@DIENST@@-intern:
    # Kein Weg nach draussen. Der Runner haengt nur hier.
    internal: true
  @@DIENST@@-extern: {}

volumes:
  @@DIENST@@-home: {}
"""

_DOCKER_SH_KOPF = """#!/bin/bash
# @@ZWECK@@
set -uo pipefail

cd "$(dirname "$0")"

if docker compose version >/dev/null 2>&1; then
    COMPOSE=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE=(docker-compose)
else
    echo "Weder 'docker compose' noch 'docker-compose' gefunden."
    echo "   Docker Compose ist der Standardweg fuer den isolierten Lauf."
    echo "   Ohne Docker: siehe @@READMENAME@@, Abschnitt Isolation."
    exit 1
fi

if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ ! -f .env ]; then
    echo "ANTHROPIC_API_KEY ist nicht gesetzt und es gibt keine .env."
    echo "   export ANTHROPIC_API_KEY=sk-ant-...   oder   echo 'ANTHROPIC_API_KEY=sk-ant-...' > .env"
    exit 1
fi

echo "Baue Container..."
"${COMPOSE[@]}" build || exit 1
"""

# Der Abschluss unterscheidet sich wirklich: Nightshift ist ein Lauf mit
# Ende und einem Exit-Code, der 24x7-Runner ist ein Daemon, der weiterlaeuft,
# bis jemand ihn beendet.
DOCKER_SH_LAUF = """
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

DOCKER_SH_DAEMON = """
echo "Starte den @@DIENST@@-Runner im Container..."
"${COMPOSE[@]}" up -d || exit 1

echo ""
echo "Der Runner laeuft im Hintergrund und wartet auf Tasks."
echo "Tasks legst du weiter auf dem Host ab: @@HOSTPFAD@@/inbox/<name>/task.md"
echo "Der Ordner ist in den Container gemountet, der Runner sieht ihn sofort."
echo ""
echo "Mitlesen:  ${COMPOSE[*]} logs -f @@DIENST@@"
echo "Beenden:   ${COMPOSE[*]} down"
echo ""

if [ "${1:-}" = "--logs" ]; then
    "${COMPOSE[@]}" logs -f @@DIENST@@
fi
exit 0
"""

# Die Isolationspruefung, die beide Runner vor dem ersten Claude-Aufruf
# ausfuehren. Gemessen wird am Kernel, nicht an einer Variablen.
_ISOLATION_MESSEN = """# ── Isolationspruefung ──────────────────────────────────────
# Isolation wird gemessen, nicht behauptet. Frueher genuegte ein Wort in
# @@SANDBOXVAR@@, und jedes Wort kam durch; das Receipt hat dann
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
    # @@PROFILNAME@@-Profil verbietet genau das, eine nackte Shell kann es
    # immer. Die Gegenprobe auf @@GEGENSTAND_AKK@@ schliesst den Fall aus, dass
    # hier gerade ueberhaupt nichts lesbar ist.
    if [ "$(uname -s 2>/dev/null)" = "Darwin" ] \\
       && ls "$@@PFADSHELL@@" >/dev/null 2>&1 \\
       && ! ls /Users >/dev/null 2>&1; then
        echo seatbelt; return 0
    fi
    echo keine
}

ISOLATION="$(isolation_messen)"
BEHAUPTET="${@@SANDBOXVAR@@:-}"
if [ -n "$BEHAUPTET" ] && [ "$BEHAUPTET" != "$ISOLATION" ]; then
    echo "@@SANDBOXVAR@@ sagt '$BEHAUPTET', gemessen wurde '$ISOLATION'."
    echo "   Die Variable schaltet keine Isolation frei, sie wird geprueft."
    echo "   Standardweg:  ./@@DOCKERSKRIPT@@"
    echo "   macOS-Option: sandbox-exec -f @@PROFILDATEI@@ ./@@STARTSKRIPT@@"
    echo "   Abbruch."
    exit 3
fi
"""

_ISOLATION_ABBRUCH = """if [ "$ISOLATION" = "keine" ]; then
    echo "WARNUNG: Dieser Lauf ist nicht isoliert."
    echo "   Claude startet mit --dangerously-skip-permissions und haette"
    echo "   Zugriff auf alles, was dein Benutzerkonto erreicht."
    echo "   Standardweg:  ./@@DOCKERSKRIPT@@"
    echo "   macOS-Option: sandbox-exec -f @@PROFILDATEI@@ ./@@STARTSKRIPT@@"
    if [ "${@@ALLOWVAR@@:-0}" != "1" ]; then
        echo "   Abbruch. Bewusst ohne Isolation: @@ALLOWVAR@@=1 setzen."
        exit 3
    fi
    echo "   @@ALLOWVAR@@=1 ist gesetzt, der Lauf geht weiter."
fi
"""


def _fuellen(vorlage, werte):
    """Setzt die Platzhalter ein und meldet jeden, der uebrig bleibt.

    Ein vergessener Platzhalter landet sonst woertlich im Dockerfile, und das
    faellt erst auf, wenn jemand den Container baut.
    """
    for schluessel, wert in werte.items():
        vorlage = vorlage.replace("@@%s@@" % schluessel, wert)
    if "@@" in vorlage:
        rest = vorlage.split("@@")[1]
        raise SystemExit("Platzhalter @@%s@@ nicht gesetzt" % rest)
    return vorlage


def allowlist_argumente(hosts):
    """Baut die printf-Argumente fuer die tinyproxy-Allowlist."""
    return " ".join("'^" + host.replace(".", "\\.") + "$'" for host in hosts)


def dockerfile(werte):
    return _fuellen(_DOCKERFILE, werte)


def compose(werte):
    return _fuellen(_COMPOSE, werte)


def docker_sh(werte, abschluss):
    return _fuellen(_DOCKER_SH_KOPF + abschluss, werte)


def isolation_messen(werte):
    return _fuellen(_ISOLATION_MESSEN, werte)


def isolation_abbruch(werte):
    return _fuellen(_ISOLATION_ABBRUCH, werte)


# Das Seatbelt-Profil. Nur macOS, und nur die Schreibseite haelt wirklich.
# Ein Profil, das auch das Lesen sperrt, startet auf aktuellem macOS kein
# Programm mehr; die Begruendung steht im Profil selbst.
_SANDBOX_SB = """(version 1)
(deny default)

; Was dieses Profil leistet: es begrenzt das Schreiben auf @@GEGENSTAND_AKK@@
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
(allow file-read* (subpath "@@HOME@@/.claude"))
(allow file-read* (subpath "@@HOME@@/.npm-global"))
(allow file-read* (subpath "@@HOME@@/.config"))
(allow file-read* (subpath "@@HOME@@/.bun"))
(allow file-read* (subpath "@@HOME@@/.nvm"))
(allow file-read* (subpath "@@HOME@@/.cargo"))

; Ohne diese Geraete laeuft keine Shell: schon "irgendwas >/dev/null"
; scheitert sonst mit "Operation not permitted".
(allow file-write* (literal "/dev/null") (literal "/dev/zero")
                   (literal "/dev/random") (literal "/dev/urandom")
                   (literal "/dev/stdout") (literal "/dev/stderr")
                   (literal "/dev/tty") (literal "/dev/dtracehelper")
                   (literal "/dev/ptmx"))

(allow file-read* file-write* (subpath "/tmp"))
(allow file-read* file-write* (subpath "/private/tmp"))
; Zuletzt, damit die @@FREIGABENAME@@ die Home-Sperre oben schlaegt, wenn
; @@GEGENSTAND@@ unterhalb von /Users liegt.
(allow file-read* file-write* (subpath "@@HOSTPFAD@@"))
"""


def sandbox_profil(werte):
    return _fuellen(_SANDBOX_SB, werte)


# ════════════════════════════════════════════════════════════
#  Watchdog: erkennen war die eine Haelfte, reagieren die andere
# ════════════════════════════════════════════════════════════
# Bis Welle 6 hat der Watchdog einen Stillstand erkannt und dann nichts
# getan: eine Zeile auf stdout und eine Notification, die nachts niemand
# sieht. Die Reaktion steht jetzt hier, einmal fuer beide Runner.
#
# Die Regel, die den Neustart sicher macht, ist die Reihenfolge: neu
# gestartet wird nur ein Lauf, den der Watchdog gerade selbst beendet hat.
# Ein Lauf, der von allein zu Ende ist, hat keine lebende PID mehr, und
# damit ist auch der Budget-Stop abgedeckt: der beendet den Lauf, also
# findet der Watchdog danach nichts mehr zum Neustarten.
_WATCHDOG_REAKTION = """
# ── Reaktion auf Stillstand ─────────────────────────────────
# melden    nur Meldung und Notification (Voreinstellung)
# beenden   Lauf beenden und selbst aussteigen
# neustart  Lauf beenden und neu starten, hoechstens @@NEUSTARTVAR@@ mal
AKTION="${@@AKTIONVAR@@:-melden}"
NEUSTARTS="${@@NEUSTARTVAR@@:-1}"
FRIST="${@@FRISTVAR@@:-20}"
PIDDATEI="${@@PIDVAR@@:-@@PIDDATEI@@}"

prozess_lebt() {
    kill -0 "$1" 2>/dev/null || return 1
    # Ein Zombie ist beendet, nur noch nicht abgeholt: sein Elternprozess
    # hat den Rueckgabewert nicht gelesen. "kill -0" sagt bei ihm trotzdem
    # ja, und ohne diese Abfrage haelt der Watchdog einen abgestuerzten Lauf
    # fuer lebendig und ruehrt sich nie wieder. Fehlt ps, bleibt es beim
    # alten Verhalten.
    ZUSTAND=$(ps -o state= -p "$1" 2>/dev/null | tr -d ' ')
    case "$ZUSTAND" in Z*) return 1 ;; esac
    return 0
}

lauf_pid() {
    [ -f "$PIDDATEI" ] || return 1
    PID=$(cat "$PIDDATEI" 2>/dev/null)
    case "${PID:-}" in ''|*[!0-9]*) return 1 ;; esac
    prozess_lebt "$PID" || return 1
    printf '%s' "$PID"
}

lauf_beenden() {
    # Erst TERM: der Runner hat einen Trap darauf und beendet Claude
    # geordnet. Erst wenn er die Frist verstreichen laesst, kommt KILL.
    kill -TERM "$1" 2>/dev/null
    WARTE=0
    while [ "$WARTE" -lt "$FRIST" ]; do
        prozess_lebt "$1" || return 0
        sleep 1
        WARTE=$((WARTE + 1))
    done
    kill -KILL "$1" 2>/dev/null
    sleep 1
    prozess_lebt "$1" && return 1
    return 0
}

stillstand_behandeln() {
    case "$AKTION" in
        beenden|neustart) ;;
        *) return 0 ;;
    esac

    PID=$(lauf_pid) || {
        echo "   Kein laufender @@MARKE@@-Prozess in $PIDDATEI."
        echo "   Der Lauf ist schon zu Ende, hier wird nichts neu gestartet."
        echo "   Ein Budget-Stop sieht genau so aus, und das ist Absicht."
        return 0
    }

    echo "   Beende PID $PID (TERM, nach ${FRIST}s KILL)..."
    if lauf_beenden "$PID"; then
        echo "   Beendet."
    else
        echo "   PID $PID laesst sich nicht beenden, von Hand nachsehen."
        return 0
    fi
    rm -f "$PIDDATEI"

    if [ "$AKTION" = "beenden" ]; then
        echo "   Aktion 'beenden': der Watchdog steigt hier aus."
        exit 0
    fi

    if [ "$NEUSTARTS" -le 0 ]; then
        echo "   Neustartbudget aufgebraucht, der Watchdog steigt hier aus."
        exit 0
    fi
    NEUSTARTS=$((NEUSTARTS - 1))
    echo "   Neustart, danach noch $NEUSTARTS uebrig."
    ( cd "$(dirname "$0")" && bash ./@@STARTSKRIPT@@ ) || \\
        echo "   Neustart fehlgeschlagen."
    # Ohne das faende der naechste Durchlauf denselben alten Zeitstempel
    # und wuerde sofort wieder zuschlagen.
    touch "$HEARTBEAT" 2>/dev/null || true
}
"""


def watchdog_reaktion(werte):
    return _fuellen(_WATCHDOG_REAKTION, werte)


# ════════════════════════════════════════════════════════════
#  Kostenzaehler und Receipt: dieselbe Rechnung fuer beide Skills
# ════════════════════════════════════════════════════════════
# Bis Welle 7 zaehlte nur Nightshift mit. 24x7 lief unbegrenzt, und weil sein
# Leerlauf Claude aufruft statt zu schlafen, kostete ein leerer Posteingang
# fast so viel wie ein voller. Die Preistabelle steht deshalb hier und nicht
# im Bash-String: ein neuer Preis gehoert an eine Stelle, nicht an zwei.
#
# Zuordnung ueber den Modellnamen aus der stream-json-Ausgabe, der erste
# passende Schluessel gewinnt. Die genaueren Namen stehen deshalb oben:
# "sonnet-4-6" muss vor "sonnet" liegen, sonst rechnet der Zaehler Sonnet 4.6
# zum billigeren Tarif und das Budget greift zu spaet.
PREISE_STAND = "2026-06-24"
PREISE = [
    ("fable", 10.00, 50.00),
    ("mythos", 10.00, 50.00),
    ("opus", 5.00, 25.00),
    ("sonnet-4-6", 3.00, 15.00),
    ("sonnet", 2.00, 10.00),
    ("haiku", 1.00, 5.00),
]
# Passt kein Schluessel, rechnet der Zaehler mit der teuersten Zeile mal
# diesem Faktor. Die teuerste bekannte Zeile allein genuegt nicht: ein Modell,
# das nach PREISE_STAND erscheint, kann darueber liegen, und dann
# unterschaetzt der Fallback genau die Zahl, gegen die er da ist.
PREIS_AUFSCHLAG = 2.0

_PREISE_AWK = ";".join(
    "%s:%s:%s" % (schluessel, ein, aus) for schluessel, ein, aus in PREISE
)

_COST_SH = r"""#!/bin/bash
# @@MARKE@@-cost.sh — zaehlt Tokens mit und stoppt den Lauf beim Budget.
#
#   claude ... | tee -a log | ./@@MARKE@@-cost.sh <zustand> <usd> <tokens> <pidfile> <marker>
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
STOPMARKER="${5:-/tmp/@@MARKE@@-budget-stop}"

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
"""

# Laeuft im EXIT-Trap des Runners, also auch nach einem Abbruch. Felder, die
# niemand ermitteln kann, stehen als "unbekannt" drin und nicht als 0 oder
# null: eine Null waere eine Aussage, die niemand geprueft hat.
_RECEIPT_SH = r"""#!/bin/bash
# @@MARKE@@-receipt.sh — schreibt receipt.json und receipt.md
#
# Erwartet die Angaben in der Umgebung (setzt @@RUNNER@@):
#   NS_RUNID NS_START NS_EXIT NS_ISOLATION NS_KOSTEN NS_ZIEL
#   NS_GENRE NS_AUFGABE NS_RUNBOOK NS_STALL
set -uo pipefail

RUNID="${NS_RUNID:-unbekannt}"
START="${NS_START:-unbekannt}"
ENDE="$(date -Iseconds 2>/dev/null || date)"
EXITCODE="${NS_EXIT:-unbekannt}"
ISOLATION="${NS_ISOLATION:-unbekannt}"
KOSTEN="${NS_KOSTEN:-}"
ZIEL="${NS_ZIEL:-@@MARKE@@-receipts/$RUNID}"
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


def cost_sh(marke):
    """Der Kostenzaehler fuer einen Skill, mit eingesetzter Preistabelle."""
    return (_COST_SH
            .replace("@@MARKE@@", marke)
            .replace("@@PREISE@@", _PREISE_AWK)
            .replace("@@PREISE_STAND@@", PREISE_STAND)
            .replace("@@PREIS_AUFSCHLAG@@", "%.2f" % PREIS_AUFSCHLAG))


def receipt_sh(marke, runner):
    """Der Receipt fuer einen Skill.

    `runner` ist nur der Dateiname, der im Kopfkommentar steht: der Receipt
    liest seine Angaben aus der Umgebung, und wer das Skript aufschlaegt, soll
    sehen, wer sie setzt.
    """
    return _RECEIPT_SH.replace("@@MARKE@@", marke).replace("@@RUNNER@@", runner)
