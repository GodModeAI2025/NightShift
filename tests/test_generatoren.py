"""Prueft, dass beide Generatoren laufen und ein brauchbares Setup schreiben.

Der Test ruft die Generatoren als eigene Prozesse auf, packt die ZIP in ein
temporaeres Verzeichnis und schaut hinein.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import helfer

NIGHTSHIFT_DATEIEN = {
    "nightshift-setup/.claude/settings.json",
    "nightshift-setup/CLAUDE-nightshift.md",
    "nightshift-setup/README-nightshift.md",
    "nightshift-setup/nightshift-run-bg.sh",
    "nightshift-setup/nightshift-run.sh",
    "nightshift-setup/nightshift-sandbox.sb",
    "nightshift-setup/nightshift-watchdog.sh",
    "nightshift-setup/runbook.md",
}

VIERUNDZWANZIG_DATEIEN = {
    "24x7-setup/.claude/settings.json",
    "24x7-setup/CLAUDE.md",
    "24x7-setup/README.md",
    "24x7-setup/failed/.gitkeep",
    "24x7-setup/idle/idle-tasks.md",
    "24x7-setup/inbox/.gitkeep",
    "24x7-setup/inbox/beispiel-task/materials/.gitkeep",
    "24x7-setup/inbox/beispiel-task/task.md",
    "24x7-setup/outbox/.gitkeep",
    "24x7-setup/runner-bg.sh",
    "24x7-setup/runner.sh",
    "24x7-setup/sandbox.sb",
    "24x7-setup/watchdog.sh",
    "24x7-setup/working/.gitkeep",
}


class GeneratorTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp(prefix="nightshift-tests-")
        cls.zips = {
            name: helfer.baue_zip(name, cls.ordner) for name in helfer.GENERATOREN
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def test_nightshift_zip_enthaelt_genau_die_erwarteten_dateien(self):
        self.assertEqual(
            NIGHTSHIFT_DATEIEN, set(helfer.zip_eintraege(self.zips["nightshift"]))
        )

    def test_24x7_zip_enthaelt_genau_die_erwarteten_dateien(self):
        self.assertEqual(
            VIERUNDZWANZIG_DATEIEN, set(helfer.zip_eintraege(self.zips["24x7"]))
        )

    def test_settings_json_ist_gueltiges_json_mit_allen_hook_ereignissen(self):
        for name, zip_pfad in self.zips.items():
            praefix = helfer.GENERATOREN[name]["praefix"]
            settings = helfer.settings_aus_zip(zip_pfad, praefix)
            for ereignis in helfer.GENERATOREN[name]["hook_ereignisse"]:
                self.assertIn(ereignis, settings["hooks"], "%s: %s" % (name, ereignis))
            kommando = helfer.pretooluse_kommando(settings)
            self.assertTrue(kommando.strip(), "%s: leeres Hook-Kommando" % name)

    def test_erzeugte_shellskripte_sind_syntaktisch_gueltig(self):
        for name, zip_pfad in self.zips.items():
            skripte = [e for e in helfer.zip_eintraege(zip_pfad) if e.endswith(".sh")]
            self.assertTrue(skripte, "%s: keine Shellskripte in der ZIP" % name)
            for eintrag in skripte:
                inhalt = helfer.datei_aus_zip(zip_pfad, eintrag)
                self.assertTrue(
                    inhalt.startswith("#!/bin/bash"),
                    "%s: kein Shebang" % eintrag,
                )
                pfad = os.path.join(self.ordner, os.path.basename(eintrag))
                with open(pfad, "w") as datei:
                    datei.write(inhalt)
                lauf = subprocess.run(
                    ["bash", "-n", pfad],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                self.assertEqual(
                    0,
                    lauf.returncode,
                    "%s: bash -n meldet %s"
                    % (eintrag, lauf.stderr.decode("utf-8", "replace")),
                )

    def test_projektpfad_landet_in_runbook_und_sandboxprofil(self):
        pfad = helfer.GENERATOREN["nightshift"]["env"]["NIGHTSHIFT_PROJECT"]
        zip_pfad = self.zips["nightshift"]
        runbook = helfer.datei_aus_zip(zip_pfad, "nightshift-setup/runbook.md")
        self.assertIn(pfad, runbook)
        profil = helfer.datei_aus_zip(
            zip_pfad, "nightshift-setup/nightshift-sandbox.sb"
        )
        self.assertIn('(allow file-read* file-write* (subpath "%s"))' % pfad, profil)

    def test_24x7_readme_kopiert_claude_verzeichnis_in_eigenem_schritt(self):
        # Das Glob * erfasst keine Dotfiles. Ohne einen eigenen Schritt fuer
        # .claude laeuft der Daemon ohne Hooks.
        readme = helfer.datei_aus_zip(self.zips["24x7"], "24x7-setup/README.md")
        self.assertIn("/.claude/.", readme)

    def test_runbook_validierung_meldet_volle_punktzahl(self):
        # Der Generator gibt die 15 Checks auf stdout aus. Faellt einer, ist die
        # Vorlage kaputt, aus der jedes Runbook entsteht.
        ordner = tempfile.mkdtemp(prefix="nightshift-validierung-")
        try:
            konfig = helfer.GENERATOREN["nightshift"]
            umgebung = dict(os.environ)
            umgebung["NIGHTSHIFT_PROJECT"] = konfig["env"]["NIGHTSHIFT_PROJECT"]
            umgebung["NIGHTSHIFT_OUT"] = os.path.join(ordner, "n.zip")
            lauf = subprocess.run(
                [sys.executable, konfig["skript"]],
                env=umgebung,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            ausgabe = lauf.stdout.decode("utf-8", "replace")
            self.assertIn("15/15", ausgabe, ausgabe)
        finally:
            shutil.rmtree(ordner, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
