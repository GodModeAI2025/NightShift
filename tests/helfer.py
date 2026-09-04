"""Gemeinsame Hilfen fuer die Tests.

Muss unter Python 3.9 laufen, das ist die dokumentierte Untergrenze.
Nur Standardbibliothek, keine Abhaengigkeiten.
"""

import json
import os
import subprocess
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Testwerte fuer die Pflichtvariablen der beiden Generatoren. Der Projektpfad
# liegt bewusst unter /tmp: die 15-Punkte-Validierung schlaegt bei Pfaden unter
# /home an und wuerde sonst 14/15 melden.
GENERATOREN = {
    "nightshift": {
        "skript": os.path.join(REPO, "nightshift", "scripts", "build_zip.py"),
        "zipname": "nightshift-setup.zip",
        "praefix": "nightshift-setup/",
        "env": {
            "NIGHTSHIFT_PROJECT": "/tmp/nightshift-testprojekt",
            "NIGHTSHIFT_OUT": None,  # wird auf den Zielpfad gesetzt
        },
        "ausgabevariable": "NIGHTSHIFT_OUT",
        "hook_ereignisse": ("PreToolUse", "PostToolUse", "SessionStart", "Stop"),
    },
    "24x7": {
        "skript": os.path.join(REPO, "24x7", "scripts", "build_zip.py"),
        "zipname": "24x7-setup.zip",
        "praefix": "24x7-setup/",
        "env": {
            "CLAUDE_24X7_WORKSPACE": "/tmp/24x7-testworkspace",
            "CLAUDE_24X7_OUT": None,
        },
        "ausgabevariable": "CLAUDE_24X7_OUT",
        "hook_ereignisse": ("PreToolUse", "PostToolUse"),
    },
}


def baue_zip(name, zielordner):
    """Ruft einen Generator auf und gibt den Pfad der erzeugten ZIP zurueck."""
    konfig = GENERATOREN[name]
    ziel = os.path.join(zielordner, konfig["zipname"])

    umgebung = dict(os.environ)
    for schluessel, wert in konfig["env"].items():
        umgebung[schluessel] = ziel if wert is None else wert

    lauf = subprocess.run(
        [sys.executable, konfig["skript"]],
        env=umgebung,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    ausgabe = lauf.stdout.decode("utf-8", "replace")
    if lauf.returncode != 0:
        raise AssertionError(
            "Generator %s beendet mit Exit-Code %d:\n%s"
            % (name, lauf.returncode, ausgabe)
        )
    if not os.path.isfile(ziel):
        raise AssertionError(
            "Generator %s hat keine ZIP unter %s geschrieben:\n%s"
            % (name, ziel, ausgabe)
        )
    return ziel


def zip_eintraege(zip_pfad):
    with zipfile.ZipFile(zip_pfad) as archiv:
        return sorted(archiv.namelist())


def datei_aus_zip(zip_pfad, eintrag):
    with zipfile.ZipFile(zip_pfad) as archiv:
        return archiv.read(eintrag).decode("utf-8")


def settings_aus_zip(zip_pfad, praefix):
    return json.loads(datei_aus_zip(zip_pfad, praefix + ".claude/settings.json"))


def pretooluse_kommando(settings):
    """Holt das Hook-Kommando, das Claude vor jedem Bash-Aufruf startet."""
    eintrag = settings["hooks"]["PreToolUse"][0]
    if eintrag.get("matcher") != "Bash":
        raise AssertionError("PreToolUse-Matcher ist nicht 'Bash': %r" % eintrag)
    return eintrag["hooks"][0]["command"]


def block_muster(kommando):
    """Schneidet das grep-Muster aus dem Hook-Kommando heraus.

    Die beiden Generatoren melden mit unterschiedlichem Text, das Muster selbst
    muss aber in beiden gleich sein.
    """
    teile = kommando.split("'\\''")
    if len(teile) < 3:
        raise AssertionError("kein gequotetes grep-Muster im Hook: %r" % kommando)
    return teile[1]


def hook_aufrufen(kommando, bash_kommando):
    """Schickt ein Bash-Kommando als Hook-Eingabe durch den Hook.

    Rueckgabe: (exit_code, stderr). Der Hook gibt 2 zurueck, wenn er blockt,
    und 0, wenn er das Kommando durchlaesst.
    """
    eingabe = json.dumps({"tool_input": {"command": bash_kommando}}).encode("utf-8")
    lauf = subprocess.run(
        kommando,
        shell=True,
        input=eingabe,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return lauf.returncode, lauf.stderr.decode("utf-8", "replace").strip()
