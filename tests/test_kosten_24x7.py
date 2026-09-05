"""Prueft, dass 24x7 mitzaehlt und beim Budget aufhoert.

Bis Welle 8 lief der Daemon unbegrenzt. Sein Leerlauf ruft Claude auf statt zu
schlafen, arbeitet bis zu 15 Minuten und pausiert danach 30 Sekunden; ein
leerer Posteingang kostete damit fast so viel wie ein voller, und niemand
konnte eine Grenze setzen.

Der Zaehler ist derselbe, den Nightshift benutzt. Neu ist nur, wie er ueber
viele Aufrufe hinweg wirkt: er sieht immer einen Strom, deshalb bekommt er vor
jedem Aufruf den Rest des Budgets und nicht die Gesamtsumme. Die Tests unten
messen genau das, an einem echten Lauf gegen einen claude-Ersatz.
"""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile

import helfer

EIN_AUFRUF_USD = 0.0175   # 1000 Ein- und 500 Ausgabe-Tokens zum Opus-Tarif
STROM = ('{"type":"assistant","message":{"model":"claude-opus-5",'
         '"usage":{"input_tokens":1000,"output_tokens":500}}}')

WERKZEUGE = ("bash", "cat", "date", "grep", "sed", "awk", "tr", "wc", "mkdir", "rm",
             "tee", "sleep", "head", "kill", "printf", "dirname", "basename", "ls",
             "mv", "cp", "timeout", "gtimeout", "touch", "jq", "env")


class Kosten24x7Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp(prefix="24x7-kosten-")
        cls.zip = helfer.baue_zip("24x7", cls.ordner)

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def aufbau(self, exitcode=0, schlaf=0, leerlauf=False):
        """Ein entpacktes Setup mit einem claude-Ersatz im PATH.

        Der Ersatz gibt stream-json aus, damit der Zaehler etwas zu lesen hat.
        Ohne `leerlauf` wird idle-tasks.md entfernt: sonst mischt sich der
        Leerlauf in die Summe und die Rechnung im Test stimmt nicht mehr.
        """
        wurzel = tempfile.mkdtemp(prefix="24x7-lauf-")
        self.addCleanup(shutil.rmtree, wurzel, True)
        arbeit = os.path.join(wurzel, "ws")
        os.makedirs(arbeit)
        with zipfile.ZipFile(self.zip) as archiv:
            for name in archiv.namelist():
                if name.endswith("/"):
                    continue
                rel = name.split("/", 1)[1] if "/" in name else name
                pfad = os.path.join(arbeit, rel)
                os.makedirs(os.path.dirname(pfad), exist_ok=True)
                with open(pfad, "wb") as datei:
                    datei.write(archiv.read(name))
                if rel.endswith(".sh"):
                    os.chmod(pfad, 0o755)

        binordner = os.path.join(wurzel, "bin")
        os.makedirs(binordner)
        for werkzeug in WERKZEUGE:
            gefunden = shutil.which(werkzeug)
            ziel = os.path.join(binordner, werkzeug)
            if gefunden and not os.path.exists(ziel):
                os.symlink(gefunden, ziel)

        stub = os.path.join(binordner, "claude")
        with open(stub, "w") as datei:
            datei.write("#!/bin/bash\n")
            if schlaf:
                datei.write("sleep %d\n" % schlaf)
            datei.write("echo '%s'\n" % STROM)
            datei.write("exit %d\n" % exitcode)
        os.chmod(stub, 0o755)

        if not leerlauf:
            os.remove(os.path.join(arbeit, "idle", "idle-tasks.md"))
        return arbeit, binordner

    def task(self, arbeit, name):
        os.makedirs(os.path.join(arbeit, "inbox", name, "materials"), exist_ok=True)
        with open(os.path.join(arbeit, "inbox", name, "task.md"), "w") as datei:
            datei.write("Mach etwas.\n")

    def starte(self, arbeit, binordner, budget, frist=40, zusatz=None):
        """Faehrt den Runner. Ein Daemon endet nicht von selbst.

        Kommt er ohne Budget-Stop bis zur Frist, ist das kein Fehlschlag,
        sondern der Normalfall; der Rueckgabewert ist dann None.
        """
        umgebung = dict(os.environ)
        umgebung.update({
            "PATH": binordner + os.pathsep + os.environ.get("PATH", ""),
            "CLAUDE_24X7_WORKSPACE": arbeit,
            "CLAUDE_24X7_ALLOW_UNSANDBOXED": "1",
            "CLAUDE_24X7_BUDGET_USD": budget,
            "CLAUDE_24X7_PIDDATEI": os.path.join(arbeit, "lauf.pid"),
        })
        if zusatz:
            umgebung.update(zusatz)
        try:
            lauf = subprocess.run(
                ["bash", os.path.join(arbeit, "runner.sh")],
                env=umgebung, cwd=arbeit, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, timeout=frist,
            )
            return lauf.returncode, lauf.stdout.decode("utf-8", "replace")
        except subprocess.TimeoutExpired as ausgelaufen:
            return None, (ausgelaufen.stdout or b"").decode("utf-8", "replace")

    def summe(self, arbeit):
        with open(os.path.join(arbeit, "24x7-kosten.json")) as datei:
            return json.load(datei)

    def inhalt(self, arbeit, ordner):
        return sorted(
            eintrag for eintrag in os.listdir(os.path.join(arbeit, ordner))
            if not eintrag.startswith(".")
        )

    def test_ein_task_unter_budget_wird_gezaehlt_und_laeuft_durch(self):
        arbeit, binordner = self.aufbau()
        code, ausgabe = self.starte(arbeit, binordner, "50.00", frist=20)
        self.assertIsNone(code, "der Daemon haette weiterlaufen muessen:\n%s" % ausgabe)
        summe = self.summe(arbeit)
        self.assertFalse(summe["budget_ueberschritten"], ausgabe)
        self.assertTrue(summe["summe_vollstaendig"], ausgabe)
        self.assertAlmostEqual(EIN_AUFRUF_USD, summe["usd_geschaetzt"], places=4)
        self.assertEqual(1000, summe["tokens_ein"])
        self.assertEqual(500, summe["tokens_aus"])

    def test_ein_zu_teurer_aufruf_beendet_den_daemon_mit_neun(self):
        arbeit, binordner = self.aufbau()
        code, ausgabe = self.starte(arbeit, binordner, "0.001")
        self.assertEqual(9, code, ausgabe)
        self.assertIn("Budget erreicht", ausgabe)
        self.assertEqual([], self.inhalt(arbeit, "outbox"), ausgabe)
        self.assertTrue(self.inhalt(arbeit, "failed"), ausgabe)
        self.assertTrue(self.summe(arbeit)["budget_ueberschritten"])

    def test_zwei_aufrufe_unter_budget_reissen_es_zusammen(self):
        """Der Kern der Sache: die Grenze gilt fuer den Lauf, nicht je Aufruf."""
        arbeit, binordner = self.aufbau()
        self.task(arbeit, "zweiter-task")
        budget = "%.4f" % (EIN_AUFRUF_USD * 1.7)      # traegt einen, nicht zwei
        code, ausgabe = self.starte(arbeit, binordner, budget)
        self.assertEqual(9, code, ausgabe)
        summe = self.summe(arbeit)
        self.assertEqual(2, summe["aufrufe"], ausgabe)
        self.assertTrue(summe["budget_ueberschritten"])
        self.assertEqual(1, len(self.inhalt(arbeit, "outbox")), ausgabe)
        self.assertEqual(1, len(self.inhalt(arbeit, "failed")), ausgabe)

    def test_die_einordnung_ueberlebt_die_pipe(self):
        """Exit 0, 1 und 124 muessen trotz Zaehler-Pipe ankommen.

        Der Rueckgabewert reist ueber eine Datei, weil das Ende der Pipeline
        dem Zaehler gehoert. Ginge das kaputt, landete jeder Task im selben
        Ordner und niemand saehe es an der Summe.
        """
        for name, exitcode, schlaf, zusatz, erwartet in (
            ("Erfolg", 0, 0, None, "outbox"),
            ("Fehler", 1, 0, None, "failed"),
            ("Zeitablauf", 0, 6, {"CLAUDE_24X7_MAX_SECONDS": "2"}, "failed"),
        ):
            with self.subTest(fall=name):
                arbeit, binordner = self.aufbau(exitcode=exitcode, schlaf=schlaf)
                _, ausgabe = self.starte(arbeit, binordner, "50.00", frist=25, zusatz=zusatz)
                anderer = "failed" if erwartet == "outbox" else "outbox"
                self.assertEqual(1, len(self.inhalt(arbeit, erwartet)), ausgabe)
                self.assertEqual([], self.inhalt(arbeit, anderer), ausgabe)

    def test_der_leerlauf_zaehlt_gegen_dasselbe_budget(self):
        """Ohne das waere die Grenze auf einem leeren Posteingang wirkungslos.

        Genau dort entstehen die Kosten: der Leerlauf arbeitet bis zu 15
        Minuten und pausiert danach 30 Sekunden.
        """
        arbeit, binordner = self.aufbau(leerlauf=True)
        for task in self.inhalt(arbeit, "inbox"):
            shutil.rmtree(os.path.join(arbeit, "inbox", task))
        code, ausgabe = self.starte(arbeit, binordner, "0.001", frist=30,
                                    zusatz={"CLAUDE_24X7_IDLE_SECONDS": "10"})
        self.assertEqual(9, code, ausgabe)
        self.assertIn("Leerlauf", ausgabe)
        self.assertTrue(self.summe(arbeit)["budget_ueberschritten"])

    def test_jeder_task_bekommt_seinen_receipt(self):
        arbeit, binordner = self.aufbau()
        _, ausgabe = self.starte(arbeit, binordner, "50.00", frist=20)
        ziel = self.inhalt(arbeit, "outbox")
        self.assertEqual(1, len(ziel), ausgabe)
        ordner = os.path.join(arbeit, "outbox", ziel[0])
        for name in ("cost.json", "receipt.json", "receipt.md"):
            self.assertTrue(os.path.isfile(os.path.join(ordner, name)),
                            "%s fehlt in %s: %s" % (name, ordner, os.listdir(ordner)))


if __name__ == "__main__":
    unittest.main()
