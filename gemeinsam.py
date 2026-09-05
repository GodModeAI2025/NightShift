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
