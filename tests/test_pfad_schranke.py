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

    def wurzelvariable(self, skill):
        """Die Variable, aus der der Hook zur Laufzeit seine Wurzel nimmt."""
        return {"nightshift": "NIGHTSHIFT_PROJEKT",
                "24x7": "CLAUDE_24X7_WORKSPACE"}[skill]

    def echte_wurzel(self):
        """Ein Projektordner, den es wirklich gibt, mit zwei Links hinaus.

        Die uebrigen Tests fahren gegen den Pfad, der beim Generieren gesetzt
        war; ob es ihn gibt, ist ihnen egal. Fuer Symlinks geht das nicht: die
        muessen auf der Platte liegen, sonst ist nichts aufzuloesen.
        """
        wurzel = tempfile.mkdtemp(prefix="pfadschranke-echt-")
        self.addCleanup(shutil.rmtree, wurzel, True)
        os.makedirs(os.path.join(wurzel, "unter"))
        os.makedirs(os.path.join(wurzel, ".claude"))
        os.symlink("/etc", os.path.join(wurzel, "raus"))
        os.symlink("/etc/hosts", os.path.join(wurzel, "fremde-datei"))
        os.symlink(os.path.join(wurzel, ".claude", "settings.json"),
                   os.path.join(wurzel, "harmlos.json"))
        return wurzel

    def test_ein_link_aus_dem_projekt_heraus_wird_geblockt(self):
        """Die Luecke, die der Textvergleich offen liess.

        Vorher wurde nur die Schreibweise verglichen. Ein Link im Projekt sah
        damit aus wie ein Ziel im Projekt, und ein Write darauf landete
        ausserhalb. Jetzt loest der Hook beide Seiten physisch auf.
        """
        wurzel = self.echte_wurzel()
        faelle = [
            (os.path.join(wurzel, "raus", "hosts"), "Link auf einen Ordner draussen"),
            (os.path.join(wurzel, "fremde-datei"), "Link auf eine Datei draussen"),
            (os.path.join(wurzel, "raus", "neu", "tief.txt"), "durch den Link in Neuland"),
        ]
        for name, kommando in self.kommandos.items():
            for ziel, warum in faelle:
                with self.subTest(skill=name, fall=warum):
                    code, fehler = helfer.pfad_hook_aufrufen(
                        kommando, "Write", ziel, wurzel,
                        {self.wurzelvariable(name): wurzel},
                    )
                    self.assertEqual(2, code, "%s: %s\n%s" % (name, ziel, fehler))
                    self.assertIn("zeigt auf", fehler,
                                  "die Meldung soll das Ziel hinter dem Link nennen")

    def test_ein_link_auf_die_hook_konfiguration_bleibt_tabu(self):
        """Sonst waere die Regel mit einem Link zu umgehen."""
        wurzel = self.echte_wurzel()
        ziel = os.path.join(wurzel, "harmlos.json")
        for name, kommando in self.kommandos.items():
            with self.subTest(skill=name):
                code, fehler = helfer.pfad_hook_aufrufen(
                    kommando, "Write", ziel, wurzel,
                    {self.wurzelvariable(name): wurzel},
                )
                self.assertEqual(2, code, fehler)
                self.assertIn("Hook-Konfiguration", fehler)

    def test_derselbe_ordner_unter_zwei_namen_kommt_durch(self):
        """/tmp und /private/tmp sind auf macOS ein Ordner, nicht zwei.

        Vorher fiel das zugunsten der Sperre aus: derselbe erlaubte Ordner
        wurde abgewiesen, weil die Schreibweise nicht passte. Da beide Seiten
        jetzt aufgeloest werden, faellt es gar nicht mehr an.
        """
        wurzel = self.echte_wurzel()
        echt = os.path.realpath(wurzel)
        if echt == wurzel:
            raise unittest.SkipTest("hier zeigt der Temp-Pfad nicht ueber einen Link")
        for name, kommando in self.kommandos.items():
            with self.subTest(skill=name):
                code, fehler = helfer.pfad_hook_aufrufen(
                    kommando, "Write", os.path.join(echt, "notiz.md"), wurzel,
                    {self.wurzelvariable(name): wurzel},
                )
                self.assertEqual(0, code, "%s: %s" % (name, fehler))

    def test_schreiben_im_projekt_geht_weiter(self):
        """Gegenprobe zur Aufloesung: was drinnen liegt, bleibt erlaubt."""
        wurzel = self.echte_wurzel()
        for name, kommando in self.kommandos.items():
            for ziel in (os.path.join(wurzel, "notiz.md"),
                         os.path.join(wurzel, "unter", "x.md"),
                         os.path.join(wurzel, "neu", "tief", "y.md")):
                with self.subTest(skill=name, ziel=ziel):
                    code, fehler = helfer.pfad_hook_aufrufen(
                        kommando, "Write", ziel, wurzel,
                        {self.wurzelvariable(name): wurzel},
                    )
                    self.assertEqual(0, code, "%s: %s\n%s" % (name, ziel, fehler))

    def test_eine_wurzel_die_es_noch_nicht_gibt_wird_genauso_behandelt(self):
        """Die Aufloesung darf nicht daran haengen, ob der Ordner schon da ist.

        Ein Setup wird oft erzeugt, bevor das Projekt existiert, und der
        Auffloeser nimmt fuer einen fehlenden Ordner einen anderen Weg als fuer
        einen vorhandenen: er spaltet ab, was es nicht gibt, und loest erst den
        naechsten existierenden Vorfahren auf. Beide Wege muessen zum selben
        Urteil fuehren.
        """
        vorhanden = tempfile.mkdtemp(prefix="pfadschranke-da-", dir="/tmp")
        self.addCleanup(shutil.rmtree, vorhanden, True)
        fehlend = os.path.join("/tmp", os.path.basename(vorhanden) + "-nicht-da")
        for name, kommando in self.kommandos.items():
            for wurzel in (vorhanden, fehlend):
                with self.subTest(skill=name, wurzel=wurzel):
                    code, fehler = helfer.pfad_hook_aufrufen(
                        kommando, "Write", os.path.join(wurzel, "x.md"), wurzel,
                        {self.wurzelvariable(name): wurzel},
                    )
                    self.assertEqual(0, code, "%s: %s\n%s" % (name, wurzel, fehler))

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
