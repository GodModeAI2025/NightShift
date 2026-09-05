"""Prueft, was der Watchdog bei Stillstand tut.

Erkannt hat er einen Stillstand schon immer. Getan hat er nichts: eine Zeile
auf stdout und eine Notification, die nachts niemand sieht. Der Test faehrt
die drei Aktionen gegen einen Scheinlauf, damit die Reaktion gemessen ist und
nicht behauptet.

Der Scheinlauf ist ein `sleep`, dessen PID in der PID-Datei steht. Der
Heartbeat ist eine Datei mit altem Zeitstempel. Beide Pfade kommen aus
Umgebungsvariablen, damit der Test keinen echten Lauf auf der Maschine
anfasst.
"""

import os
import shutil
import signal
import subprocess
import tempfile
import time
import unittest

import helfer

SKILLS = {
    "nightshift": {
        "praefix": "nightshift-setup/",
        "watchdog": "nightshift-watchdog.sh",
        "startskript": "nightshift-run-bg.sh",
        "aktionvar": "NIGHTSHIFT_WATCHDOG_AKTION",
        "neustartvar": "NIGHTSHIFT_WATCHDOG_NEUSTARTS",
        "fristvar": "NIGHTSHIFT_WATCHDOG_FRIST",
        "pidvar": "NIGHTSHIFT_PIDDATEI",
        "heartbeatvar": "NIGHTSHIFT_HEARTBEAT",
    },
    "24x7": {
        "praefix": "24x7-setup/",
        "watchdog": "watchdog.sh",
        "startskript": "runner-bg.sh",
        "aktionvar": "CLAUDE_24X7_WATCHDOG_AKTION",
        "neustartvar": "CLAUDE_24X7_WATCHDOG_NEUSTARTS",
        "fristvar": "CLAUDE_24X7_WATCHDOG_FRIST",
        "pidvar": "CLAUDE_24X7_PIDDATEI",
        "heartbeatvar": "CLAUDE_24X7_HEARTBEAT",
    },
}


def lebt(prozess):
    """Lebt der Scheinlauf noch?

    Nicht os.kill(pid, 0): ein beendetes Kind dieses Testprozesses bleibt
    Zombie, bis jemand seinen Rueckgabewert abholt, und kill sagt bei einem
    Zombie ja. poll() holt ihn ab und beantwortet damit die Frage, die hier
    gemeint ist.
    """
    return prozess.poll() is None


class WatchdogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp(prefix="nightshift-watchdog-")
        cls.zips = {name: helfer.baue_zip(name, cls.ordner) for name in SKILLS}

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def aufbau(self, skill, mit_startskript=True):
        """Legt Watchdog, Scheinlauf, PID-Datei und alten Heartbeat an."""
        konfig = SKILLS[skill]
        arbeit = tempfile.mkdtemp(prefix="watchdog-lauf-")
        self.addCleanup(shutil.rmtree, arbeit, True)

        watchdog = os.path.join(arbeit, konfig["watchdog"])
        with open(watchdog, "w") as datei:
            datei.write(
                helfer.datei_aus_zip(
                    self.zips[skill], konfig["praefix"] + konfig["watchdog"]
                )
            )

        # Statt des Runners ein Skript, das nur eine Spur hinterlaesst. Ein
        # echter Neustart wuerde Claude aufrufen.
        marker = os.path.join(arbeit, "neustart-passiert")
        if mit_startskript:
            start = os.path.join(arbeit, konfig["startskript"])
            with open(start, "w") as datei:
                datei.write("#!/bin/bash\necho neustart >> '%s'\n" % marker)

        scheinlauf = subprocess.Popen(["sleep", "300"])
        self.addCleanup(self.aufraeumen, scheinlauf)

        piddatei = os.path.join(arbeit, "lauf.pid")
        with open(piddatei, "w") as datei:
            datei.write("%d\n" % scheinlauf.pid)

        heartbeat = os.path.join(arbeit, "heartbeat.log")
        with open(heartbeat, "w") as datei:
            datei.write("alt\n")
        alt = time.time() - 3600
        os.utime(heartbeat, (alt, alt))

        umgebung = dict(os.environ)
        umgebung[konfig["pidvar"]] = piddatei
        umgebung[konfig["heartbeatvar"]] = heartbeat
        umgebung[konfig["fristvar"]] = "3"
        return arbeit, watchdog, scheinlauf, piddatei, marker, umgebung

    def aufraeumen(self, prozess):
        if prozess.poll() is None:
            prozess.kill()
        prozess.wait()

    def starte_watchdog(self, watchdog, arbeit, umgebung, sekunden=25):
        """Startet den Watchdog mit Timeout 1 und wartet auf sein Ende."""
        protokoll = os.path.join(arbeit, "watchdog.log")
        with open(protokoll, "w") as datei:
            lauf = subprocess.Popen(
                ["bash", watchdog, "1"],
                cwd=arbeit,
                env=umgebung,
                stdout=datei,
                stderr=subprocess.STDOUT,
            )
        try:
            grenze = time.time() + sekunden
            while time.time() < grenze and lauf.poll() is None:
                time.sleep(0.2)
        finally:
            if lauf.poll() is None:
                lauf.terminate()
                lauf.wait()
        with open(protokoll) as datei:
            return lauf.returncode, datei.read()

    def test_melden_ist_die_voreinstellung_und_beendet_nichts(self):
        # Wer nichts einstellt, bekommt das alte Verhalten: melden, weiter.
        for skill in SKILLS:
            arbeit, watchdog, lauf, _pid, marker, umgebung = self.aufbau(skill)
            code, ausgabe = self.starte_watchdog(watchdog, arbeit, umgebung, 6)
            self.assertIn("KEIN HEARTBEAT", ausgabe, skill)
            self.assertIn("Aktion: melden", ausgabe, skill)
            self.assertTrue(lebt(lauf), "%s: Lauf wurde beendet" % skill)
            self.assertFalse(os.path.exists(marker), skill)

    def test_beenden_beendet_den_lauf_und_steigt_aus(self):
        for skill, konfig in SKILLS.items():
            arbeit, watchdog, lauf, piddatei, marker, umgebung = self.aufbau(skill)
            umgebung[konfig["aktionvar"]] = "beenden"
            code, ausgabe = self.starte_watchdog(watchdog, arbeit, umgebung)
            self.assertEqual(0, code, "%s: %s" % (skill, ausgabe))
            self.assertIn("Beendet.", ausgabe, skill)
            self.assertFalse(lebt(lauf), "%s: Lauf laeuft noch" % skill)
            self.assertFalse(os.path.exists(piddatei), skill)
            self.assertFalse(os.path.exists(marker), "%s: hat neu gestartet" % skill)

    def test_neustart_beendet_und_startet_wieder(self):
        for skill, konfig in SKILLS.items():
            arbeit, watchdog, lauf, _pid, marker, umgebung = self.aufbau(skill)
            umgebung[konfig["aktionvar"]] = "neustart"
            umgebung[konfig["neustartvar"]] = "1"
            code, ausgabe = self.starte_watchdog(watchdog, arbeit, umgebung)
            self.assertFalse(lebt(lauf), "%s: Lauf laeuft noch" % skill)
            self.assertTrue(
                os.path.exists(marker),
                "%s: kein Neustart, Ausgabe:\n%s" % (skill, ausgabe),
            )
            self.assertIn("Neustart, danach noch 0 uebrig", ausgabe, skill)

    def test_ein_beendeter_lauf_wird_nicht_neu_gestartet(self):
        """Die Regel, die den Budget-Stop schuetzt.

        Neu gestartet wird nur ein Lauf, den der Watchdog gerade selbst
        beendet hat. Ein Lauf, der von allein zu Ende ist, hat keine lebende
        PID mehr, und ein Budget-Stop sieht genau so aus.
        """
        for skill, konfig in SKILLS.items():
            arbeit, watchdog, lauf, _pid, marker, umgebung = self.aufbau(skill)
            umgebung[konfig["aktionvar"]] = "neustart"
            lauf.kill()
            lauf.wait()
            code, ausgabe = self.starte_watchdog(watchdog, arbeit, umgebung, 6)
            self.assertIn("Der Lauf ist schon zu Ende", ausgabe, skill)
            self.assertFalse(
                os.path.exists(marker),
                "%s: hat einen beendeten Lauf neu gestartet" % skill,
            )

    def test_neustartbudget_null_beendet_nur(self):
        for skill, konfig in SKILLS.items():
            arbeit, watchdog, lauf, _pid, marker, umgebung = self.aufbau(skill)
            umgebung[konfig["aktionvar"]] = "neustart"
            umgebung[konfig["neustartvar"]] = "0"
            code, ausgabe = self.starte_watchdog(watchdog, arbeit, umgebung)
            self.assertEqual(0, code, "%s: %s" % (skill, ausgabe))
            self.assertFalse(lebt(lauf), skill)
            self.assertIn("Neustartbudget aufgebraucht", ausgabe, skill)
            self.assertFalse(os.path.exists(marker), skill)

    def test_unbekannte_aktion_verhaelt_sich_wie_melden(self):
        # Ein Tippfehler in der Variablen darf keinen Lauf beenden.
        for skill, konfig in SKILLS.items():
            arbeit, watchdog, lauf, _pid, marker, umgebung = self.aufbau(skill)
            umgebung[konfig["aktionvar"]] = "abschiessen"
            code, ausgabe = self.starte_watchdog(watchdog, arbeit, umgebung, 6)
            self.assertIn("KEIN HEARTBEAT", ausgabe, skill)
            self.assertTrue(lebt(lauf), "%s: Lauf wurde beendet" % skill)
            self.assertFalse(os.path.exists(marker), skill)

    def test_der_lauf_bekommt_erst_TERM_und_darf_aufraeumen(self):
        """Kein sofortiges KILL: der Runner haengt einen Trap an TERM.

        Der Scheinlauf faengt TERM ab, schreibt eine Spur und beendet sich.
        Die Spur beweist, dass der Watchdog nicht direkt mit KILL kommt.
        """
        skill = "nightshift"
        konfig = SKILLS[skill]
        arbeit, watchdog, lauf, piddatei, marker, umgebung = self.aufbau(skill)
        # Den Scheinlauf durch einen ersetzen, der TERM behandelt.
        lauf.kill()
        lauf.wait()
        spur = os.path.join(arbeit, "term-empfangen")
        skript = os.path.join(arbeit, "haenger.sh")
        with open(skript, "w") as datei:
            datei.write(
                "#!/bin/bash\n"
                "trap 'echo term > \"%s\"; exit 0' TERM\n"
                "sleep 300 &\nwait\n" % spur
            )
        haenger = subprocess.Popen(["bash", skript])
        self.addCleanup(self.aufraeumen, haenger)
        with open(piddatei, "w") as datei:
            datei.write("%d\n" % haenger.pid)

        umgebung[konfig["aktionvar"]] = "beenden"
        code, ausgabe = self.starte_watchdog(watchdog, arbeit, umgebung)
        self.assertEqual(0, code, ausgabe)
        self.assertTrue(os.path.exists(spur), "kein TERM angekommen:\n%s" % ausgabe)
        self.assertFalse(lebt(haenger))


if __name__ == "__main__":
    unittest.main()
