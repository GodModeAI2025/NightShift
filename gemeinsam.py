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
