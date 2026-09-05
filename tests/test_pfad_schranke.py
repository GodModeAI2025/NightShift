"""Testtabelle fuer die Pfadschranke des PreToolUse-Hooks.

Bis Welle 6 trug PreToolUse nur "matcher": "Bash". Write, Edit und
NotebookEdit erreichten den Hook nie, ein unbeaufsichtigter Lauf konnte also
jede Datei auf der Platte schreiben, ohne dass die Schutzschicht das sah.

Der Test nimmt nicht die Quelle, sondern das Hook-Kommando aus der generierten
.claude/settings.json und schickt echte Werkzeugaufrufe als JSON hindurch.
Damit haengt jede Zeile am ganzen Pfad: jq, das Normalisieren, der Vergleich
gegen die Wurzel und der Exit-Code.

Exit 2 heisst geblockt, Exit 0 heisst durchgelassen.
"""

import os
import shutil
import subprocess
import tempfile
import unittest

import helfer

HOME = os.path.expanduser("~")


def blockieren(wurzel):
    """Schreibziele, die der Hook abweisen muss."""
    return [
        # Der Fall, um den es geht: ein Lauf schreibt sich einen Schluessel
        # in das Home des Betreibers.
        "~/.ssh/authorized_keys",
        HOME + "/.ssh/authorized_keys",
        HOME + "/.claude/settings.json",
        "/etc/passwd",
        "/etc/sudoers.d/nachtlauf",
        "/usr/local/bin/hilfsprogramm",
        # Nachbar mit demselben Praefix. Ein blosser Textvergleich ohne den
        # Schraegstrich wuerde das durchlassen.
        wurzel + "-kopie/datei.txt",
        wurzel + "2/datei.txt",
        # Ueber die Wurzel hinaus, absolut wie relativ.
        wurzel + "/../nachbar/datei.txt",
        wurzel + "/unterordner/../../nachbar/datei.txt",
        "../ausserhalb.txt",
        "../../etc/passwd",
        # Die eigene Hook-Konfiguration, obwohl sie in der Wurzel liegt.
        wurzel + "/.claude/settings.json",
        wurzel + "/.claude/settings.local.json",
    ]


def durchlassen(wurzel):
    """Schreibziele, die ein Lauf wirklich braucht."""
    return [
        wurzel + "/src/index.ts",
        wurzel + "/tief/verschachtelt/notiz.md",
        wurzel + "/nightshift-receipts/lauf/cost.json",
        # Relativ, aufgeloest gegen das Arbeitsverzeichnis aus der Eingabe.
        "src/relativ.ts",
        "./doku/relativ.md",
        "unterordner/../datei.txt",
        # Schreibweisen, die auf denselben Pfad zeigen.
        wurzel + "//doppelt//schraeg.txt",
        wurzel + "/a/../b.txt",
        # In .claude ist nur die settings.json tabu, nicht der ganze Ordner.
        wurzel + "/.claude/eigene-notiz.md",
    ]


class PfadSchrankeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if shutil.which("jq") is None:
            # Kein Skip: ohne jq blockt der Hook jeden Aufruf, die Tabelle
            # waere dann wertlos statt uebersprungen.
            raise RuntimeError("jq fehlt, der Hook ist ohne jq nicht pruefbar")
        cls.ordner = tempfile.mkdtemp(prefix="nightshift-pfadtests-")
        cls.kommandos = {}
        cls.wurzeln = {
            "nightshift": helfer.GENERATOREN["nightshift"]["env"]["NIGHTSHIFT_PROJECT"],
            "24x7": helfer.GENERATOREN["24x7"]["env"]["CLAUDE_24X7_WORKSPACE"],
        }
        for name, konfig in helfer.GENERATOREN.items():
            zip_pfad = helfer.baue_zip(name, cls.ordner)
            settings = helfer.settings_aus_zip(zip_pfad, konfig["praefix"])
            cls.kommandos[name] = helfer.pfad_kommando(settings)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def test_ziele_ausserhalb_der_wurzel_werden_geblockt(self):
        for name, kommando in self.kommandos.items():
            wurzel = self.wurzeln[name]
            for ziel in blockieren(wurzel):
                code, fehler = helfer.pfad_hook_aufrufen(
                    kommando, "Write", ziel, wurzel
                )
                self.assertEqual(
                    2,
                    code,
                    "%s: %r haette geblockt werden muessen, Exit %d, stderr %r"
                    % (name, ziel, code, fehler),
                )
                self.assertIn("BLOCKED", fehler, "%s: %r" % (name, ziel))

    def test_ziele_in_der_wurzel_kommen_durch(self):
        for name, kommando in self.kommandos.items():
            wurzel = self.wurzeln[name]
            for ziel in durchlassen(wurzel):
                code, fehler = helfer.pfad_hook_aufrufen(
                    kommando, "Write", ziel, wurzel
                )
                self.assertEqual(
                    0,
                    code,
                    "%s: %r haette durchkommen muessen, Exit %d, stderr %r"
                    % (name, ziel, code, fehler),
                )

    def test_edit_und_notebookedit_werden_genauso_geprueft(self):
        # Edit schickt file_path, NotebookEdit schickt notebook_path. Wer nur
        # den ersten Schluessel liest, laesst Notebooks ueberall hin laufen.
        for name, kommando in self.kommandos.items():
            wurzel = self.wurzeln[name]
            faelle = [
                ("Edit", wurzel + "/src/index.ts", 0),
                ("Edit", "/etc/hosts", 2),
                ("MultiEdit", wurzel + "/src/index.ts", 0),
                ("MultiEdit", HOME + "/.zshrc", 2),
                ("NotebookEdit", wurzel + "/analyse.ipynb", 0),
                ("NotebookEdit", HOME + "/geheim.ipynb", 2),
                ("NotebookEdit", "~/geheim.ipynb", 2),
            ]
            for werkzeug, ziel, erwartet in faelle:
                code, fehler = helfer.pfad_hook_aufrufen(
                    kommando, werkzeug, ziel, wurzel
                )
                self.assertEqual(
                    erwartet,
                    code,
                    "%s: %s auf %r ergab Exit %d, stderr %r"
                    % (name, werkzeug, ziel, code, fehler),
                )

    def test_eingabe_ohne_zielpfad_wird_geblockt(self):
        # Alle vier Werkzeuge bringen einen Pfad mit. Fehlt er, ist die
        # Eingabe kaputt, und eine kaputte Eingabe ist nicht pruefbar.
        for name, kommando in self.kommandos.items():
            code, fehler = helfer.pfad_hook_aufrufen(
                kommando, "Write", None, self.wurzeln[name]
            )
            self.assertEqual(2, code, "%s: Exit %d, stderr %r" % (name, code, fehler))
            self.assertIn("kein Zielpfad", fehler, name)

    def test_ohne_jq_blockt_der_hook_statt_durchzuwinken(self):
        # Fail closed. Ohne jq kann der Hook den Pfad nicht lesen, und ein
        # Hook, der dann durchlaesst, ist schlimmer als keiner.
        nurbash = tempfile.mkdtemp(prefix="nightshift-ohne-jq-")
        try:
            os.symlink(shutil.which("bash"), os.path.join(nurbash, "bash"))
            umgebung = dict(os.environ)
            umgebung["PATH"] = nurbash
            for name, kommando in self.kommandos.items():
                lauf = subprocess.run(
                    kommando,
                    shell=True,
                    env=umgebung,
                    input=b'{"tool_input":{"file_path":"/etc/passwd"}}',
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                fehler = lauf.stderr.decode("utf-8", "replace").strip()
                self.assertEqual(2, lauf.returncode, "%s: %r" % (name, fehler))
                self.assertIn("jq nicht gefunden", fehler, name)
        finally:
            shutil.rmtree(nurbash, ignore_errors=True)

    def test_beide_matcher_stehen_in_der_settings_json(self):
        for name, konfig in helfer.GENERATOREN.items():
            zip_pfad = os.path.join(self.ordner, konfig["zipname"])
            settings = helfer.settings_aus_zip(zip_pfad, konfig["praefix"])
            matcher = [e.get("matcher") for e in settings["hooks"]["PreToolUse"]]
            self.assertEqual(["Bash", helfer.PFAD_MATCHER], matcher, name)

    def test_beide_generatoren_nutzen_dieselbe_pfadlogik(self):
        # Der Rumpf steht in gemeinsam.py. Unterscheiden duerfen sich nur die
        # Meldemarke und die Wurzel, nicht die Pruefung selbst.
        rumpf = []
        for name, kommando in self.kommandos.items():
            entschaerft = kommando
            # Reihenfolge zaehlt: erst die langen Namen, sonst frisst die
            # Marke "24x7" ihren eigenen Wurzelpfad an.
            for wurzel in self.wurzeln.values():
                entschaerft = entschaerft.replace(wurzel, "@wurzel@")
            for variable in ("NIGHTSHIFT_PROJEKT", "CLAUDE_24X7_WORKSPACE"):
                entschaerft = entschaerft.replace(variable, "@variable@")
            for marke in ("NIGHTSHIFT", "24x7"):
                entschaerft = entschaerft.replace(marke, "@marke@")
            rumpf.append(entschaerft)
        self.assertEqual(rumpf[0], rumpf[1])


if __name__ == "__main__":
    unittest.main()
