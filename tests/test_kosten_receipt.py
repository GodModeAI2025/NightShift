"""Prueft Cost Governor und Morning Receipt am laufenden Skript.

Statt eines echten Claude-Aufrufs steht ein Stub im PATH, der stream-json
mit usage-Feldern ausgibt. Damit kostet der Test nichts und trotzdem laeuft
genau der Pfad, den ein Nachtlauf nimmt: messen, Budget pruefen, Prozess
beenden, Receipt schreiben.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest

import helfer

PRAEFIX = "nightshift-setup/"

# Ein Ereignis mit diesen Zahlen kostet bei Opus-Preisen
# 100000/1e6*5 + 50000/1e6*25 = 1.75 USD. Zwei Ereignisse reissen ein
# Budget von 3 USD.
EREIGNIS = (
    '{"type":"assistant","message":{"model":"claude-opus-5","usage":'
    '{"input_tokens":100000,"output_tokens":50000,'
    '"cache_creation_input_tokens":0,"cache_read_input_tokens":0}}}'
)


def stub_schreiben(pfad, zeilen, nachlauf="", mit_kind=False):
    with open(pfad, "w") as datei:
        datei.write("#!/bin/bash\n")
        if mit_kind:
            # Ein Kind, das die Pipe offen haelt. Wer beim Budget-Stopp nur
            # den Elternprozess abschiesst, haengt hier fest.
            datei.write("sleep 120 &\n")
        for zeile in zeilen:
            datei.write("echo '%s'\nsleep 0.2\n" % zeile)
        datei.write(nachlauf)
    os.chmod(pfad, 0o755)


class LaufTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp(prefix="nightshift-kosten-")
        cls.zip_pfad = helfer.baue_zip("nightshift", cls.ordner)
        cls.projekt = helfer.GENERATOREN["nightshift"]["env"]["NIGHTSHIFT_PROJECT"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def datei(self, name):
        return helfer.datei_aus_zip(self.zip_pfad, PRAEFIX + name)

    def arbeitsordner(self, stubzeilen, nachlauf="", mit_kind=False):
        arbeit = tempfile.mkdtemp(prefix="nightshift-lauf-")
        for name in (
            "nightshift-run.sh",
            "nightshift-cost.sh",
            "nightshift-receipt.sh",
            "runbook.md",
        ):
            with open(os.path.join(arbeit, name), "w") as datei:
                datei.write(self.datei(name).replace(self.projekt, arbeit))
        stubordner = os.path.join(arbeit, "bin")
        os.makedirs(stubordner)
        stub_schreiben(
            os.path.join(stubordner, "claude"), stubzeilen, nachlauf, mit_kind
        )
        return arbeit, stubordner

    def starte(self, arbeit, stubordner, zusatz):
        umgebung = dict(os.environ)
        umgebung["PATH"] = stubordner + os.pathsep + umgebung.get("PATH", "")
        umgebung["NIGHTSHIFT_PROJEKT"] = arbeit
        umgebung["NIGHTSHIFT_SANDBOXED"] = "test"
        umgebung.update(zusatz)
        lauf = subprocess.run(
            ["bash", os.path.join(arbeit, "nightshift-run.sh")],
            cwd=arbeit,
            env=umgebung,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
        )
        return lauf.returncode, lauf.stdout.decode("utf-8", "replace")

    def receipt(self, arbeit):
        wurzel = os.path.join(arbeit, "nightshift-receipts")
        laeufe = sorted(os.listdir(wurzel))
        self.assertTrue(laeufe, "kein Receipt-Ordner angelegt")
        ordner = os.path.join(wurzel, laeufe[-1])
        with open(os.path.join(ordner, "receipt.json")) as datei:
            daten = json.load(datei)
        with open(os.path.join(ordner, "receipt.md")) as datei:
            text = datei.read()
        return ordner, daten, text

    def test_budget_stoppt_den_lauf_und_weist_die_tokens_aus(self):
        arbeit, stubordner = self.arbeitsordner(
            [EREIGNIS] * 20, "sleep 120\n", mit_kind=True
        )
        try:
            code, ausgabe = self.starte(
                arbeit, stubordner, {"NIGHTSHIFT_BUDGET_USD": "3.00"}
            )
            self.assertEqual(9, code, ausgabe)
            self.assertIn("BUDGET ERREICHT", ausgabe)
            self.assertIn("BUDGET-STOP", ausgabe)

            ordner, daten, text = self.receipt(arbeit)
            with open(os.path.join(ordner, "cost.json")) as datei:
                kosten = json.load(datei)
            self.assertEqual("gemessen", kosten["status"])
            # Zwei Ereignisse bis zum Stopp, danach kein weiteres.
            self.assertEqual(200000, kosten["tokens_ein"])
            self.assertEqual(100000, kosten["tokens_aus"])
            self.assertTrue(kosten["budget_ueberschritten"])
            self.assertGreaterEqual(kosten["usd_geschaetzt"], 3.0)

            self.assertEqual(9, daten["exit_code"])
            self.assertEqual(200000, daten["kosten"]["tokens_ein"])
            # Ein Wahrheitswert gehoert als Wahrheitswert ins JSON.
            self.assertIs(True, daten["kosten"]["budget_stop"])
            self.assertIn("Budget erreicht", text)
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_lauf_unter_budget_laeuft_durch_und_zaehlt_mit(self):
        arbeit, stubordner = self.arbeitsordner(
            [EREIGNIS, '{"type":"result","total_cost_usd":1.75}']
        )
        try:
            code, ausgabe = self.starte(
                arbeit, stubordner, {"NIGHTSHIFT_BUDGET_USD": "100"}
            )
            self.assertEqual(0, code, ausgabe)
            ordner, daten, text = self.receipt(arbeit)
            with open(os.path.join(ordner, "cost.json")) as datei:
                kosten = json.load(datei)
            self.assertFalse(kosten["budget_ueberschritten"])
            self.assertEqual(100000, kosten["tokens_ein"])
            # Der von Claude gemeldete Betrag wird uebernommen, aber nicht mit
            # der eigenen Schaetzung vermischt.
            self.assertEqual(1.75, kosten["usd_gemeldet"])
            self.assertEqual(0, daten["exit_code"])
            self.assertEqual("test", daten["isolation"])
            # false ist eine Aussage, kein fehlender Wert.
            self.assertIs(False, daten["kosten"]["budget_stop"])
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_diff_im_git_projekt_wird_gezaehlt_statt_unbekannt(self):
        """Ein erfolgreiches git diff ohne Ausgabe heisst null, nicht unbekannt.

        Genau dieser Fall trifft jeden ersten Lauf: ein einziger Commit, also
        kein HEAD~1, und ein sauberer Arbeitsbaum.
        """
        arbeit, stubordner = self.arbeitsordner([EREIGNIS])
        try:
            for befehl in (
                ["git", "init", "-q", "."],
                ["git", "add", "-A"],
                ["git", "-c", "user.email=t@t", "-c", "user.name=t",
                 "commit", "-q", "-m", "start"],
            ):
                subprocess.run(befehl, cwd=arbeit, stdout=subprocess.PIPE,
                               stderr=subprocess.STDOUT, check=True)
            code, ausgabe = self.starte(arbeit, stubordner, {})
            self.assertEqual(0, code, ausgabe)
            _, daten, _ = self.receipt(arbeit)
            self.assertEqual(0, daten["diff"]["dateien"])
            self.assertEqual(0, daten["diff"]["plus"])
            self.assertEqual(0, daten["diff"]["minus"])
            self.assertNotEqual("unbekannt", daten["git_commit"])
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_receipt_entsteht_auch_wenn_der_lauf_abbricht(self):
        arbeit, stubordner = self.arbeitsordner([], "exit 42\n")
        try:
            code, ausgabe = self.starte(arbeit, stubordner, {})
            self.assertEqual(42, code, ausgabe)
            _, daten, text = self.receipt(arbeit)
            self.assertEqual(42, daten["exit_code"])
            self.assertIn("Lauf abgebrochen", text)
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_unbekanntes_bleibt_unbekannt_und_wird_nicht_zu_null(self):
        """Ohne Messung darf im Receipt keine 0 stehen.

        Der Test nimmt jq aus dem PATH. Dann kann der Zaehler nichts lesen,
        und genau das muss der Receipt sagen.
        """
        arbeit, stubordner = self.arbeitsordner([EREIGNIS])
        try:
            # Ein PATH, in dem es kein jq gibt, aber die noetigen Coreutils.
            leer = tempfile.mkdtemp(prefix="nightshift-ohne-jq-")
            for werkzeug in (
                "bash", "cat", "date", "grep", "sed", "awk", "tr", "wc",
                "mkdir", "rm", "tee", "sleep", "git", "head", "kill",
                "printf", "pkill", "dirname", "basename", "seq", "ls",
            ):
                pfad = shutil.which(werkzeug)
                if pfad:
                    ziel = os.path.join(leer, werkzeug)
                    if not os.path.exists(ziel):
                        os.symlink(pfad, ziel)
            shutil.copy(os.path.join(stubordner, "claude"), os.path.join(leer, "claude"))
            code, ausgabe = self.starte(
                arbeit, leer, {"PATH": leer, "NIGHTSHIFT_SANDBOXED": "test"}
            )
            self.assertEqual(0, code, ausgabe)
            ordner, daten, text = self.receipt(arbeit)
            with open(os.path.join(ordner, "cost.json")) as datei:
                kosten = json.load(datei)
            self.assertEqual("unbekannt", kosten["status"])
            self.assertEqual("unbekannt", daten["kosten"]["status"])
            self.assertEqual("unbekannt", daten["kosten"]["tokens_ein"])
            self.assertEqual("unbekannt", daten["kosten"]["usd_geschaetzt"])
            self.assertIn("unbekannt", text)
            shutil.rmtree(leer, ignore_errors=True)
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_receipt_enthaelt_die_fuenf_geforderten_angaben(self):
        arbeit, stubordner = self.arbeitsordner([EREIGNIS])
        try:
            code, ausgabe = self.starte(arbeit, stubordner, {})
            self.assertEqual(0, code, ausgabe)
            _, daten, text = self.receipt(arbeit)
            for feld in (
                "schritte_erledigt",
                "schritte_offen",
                "schritte_offen_liste",
                "kosten",
                "isolation",
                "git_commit",
                "diff",
                "entscheidungen_zeilen",
                "exit_code",
                "run_id",
            ):
                self.assertIn(feld, daten, feld)
            self.assertIsInstance(daten["schritte_offen_liste"], list)
            self.assertEqual(9, daten["schritte_offen"])
            self.assertIn("# Morning Receipt", text)
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
