"""Prueft die Container-Isolation, die der Nightshift-Generator erzeugt.

Zwei Ebenen. Statisch: enthaelt das Setup Dockerfile und docker-compose.yml,
mountet die Compose-Datei genau einen Hostpfad, und weigert sich der Runner
ohne Isolation zu starten. Dynamisch: laesst 'docker compose config' die
erzeugte Datei pruefen, sobald ein Compose-Kommando erreichbar ist.

Der Lauf im Container selbst gehoert nicht hierher: er braucht ein Netz, ein
Basis-Image und mehrere Minuten Bauzeit. Der Nachweis dafuer steht im
Pull-Request.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import helfer

PRAEFIX = "nightshift-setup/"


def compose_kommando():
    """Findet ein Compose-Kommando oder gibt None zurueck.

    NIGHTSHIFT_COMPOSE erlaubt es, einen eigenen Pfad vorzugeben; sonst wird
    'docker compose' probiert.
    """
    eigenes = os.environ.get("NIGHTSHIFT_COMPOSE")
    kandidaten = []
    if eigenes:
        kandidaten.append([eigenes])
    kandidaten.append(["docker", "compose"])
    kandidaten.append(["docker-compose"])
    for kandidat in kandidaten:
        try:
            lauf = subprocess.run(
                kandidat + ["version"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
        except OSError:
            continue
        if lauf.returncode == 0:
            return kandidat
    return None


def in_container():
    """Spiegelt alle vier Containersonden aus isolation_messen().

    Weniger als alle vier waere eine Luecke: laeuft die CI selbst als
    Container-Job, misst der Runner zu Recht "docker" und der Test unten
    wuerde an der eigenen Erwartung scheitern statt uebersprungen zu werden.
    """
    if os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv"):
        return True
    for pfad, muster in (
        ("/proc/1/cgroup", ("docker", "containerd", "kubepods", "libpod", "lxc")),
        ("/proc/mounts", ("overlay / ",)),
    ):
        try:
            with open(pfad) as datei:
                inhalt = datei.read()
        except (IOError, OSError):
            continue
        if pfad.endswith("mounts"):
            if any(zeile.startswith("overlay / ") for zeile in inhalt.splitlines()):
                return True
        elif any(wort in inhalt for wort in muster):
            return True
    return False


class IsolationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp(prefix="nightshift-isolation-")
        cls.zip_pfad = helfer.baue_zip("nightshift", cls.ordner)
        cls.projekt = helfer.GENERATOREN["nightshift"]["env"]["NIGHTSHIFT_PROJECT"]

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def datei(self, name):
        return helfer.datei_aus_zip(self.zip_pfad, PRAEFIX + name)

    def test_setup_enthaelt_dockerfile_und_compose(self):
        eintraege = helfer.zip_eintraege(self.zip_pfad)
        self.assertIn(PRAEFIX + "Dockerfile", eintraege)
        self.assertIn(PRAEFIX + "docker-compose.yml", eintraege)
        self.assertIn(PRAEFIX + "nightshift-docker.sh", eintraege)

    def test_dockerfile_hat_beide_ziele_und_laeuft_nicht_als_root(self):
        inhalt = self.datei("Dockerfile")
        self.assertIn("AS runner", inhalt)
        self.assertIn("AS egress", inhalt)
        self.assertIn("USER node", inhalt)
        self.assertIn("USER tinyproxy", inhalt)
        # NIGHTSHIFT_SANDBOXED ist im Container nur noch die Gegenprobe:
        # der Runner misst selbst und bricht ab, wenn die Variable etwas
        # anderes behauptet. Das Projekt liegt im Container unter /project.
        self.assertIn("NIGHTSHIFT_SANDBOXED=docker", inhalt)
        self.assertIn("NIGHTSHIFT_PROJEKT=/project", inhalt)

    def test_compose_mountet_nur_das_projekt_vom_host(self):
        inhalt = self.datei("docker-compose.yml")
        mounts = [
            zeile.strip().strip('-').strip().strip('"')
            for zeile in inhalt.splitlines()
            if zeile.strip().startswith('- "') and ":/" in zeile
        ]
        self.assertIn("%s:/project" % self.projekt, mounts)
        for mount in mounts:
            quelle = mount.split(":")[0]
            # Alles ausser dem Projekt muss ein benanntes Volume sein, also
            # ohne Schraegstrich. Ein zweiter Hostpfad waere ein Loch.
            if quelle != self.projekt:
                self.assertNotIn("/", quelle, "zweiter Hostpfad im Mount: %s" % mount)

    def test_compose_haerten_und_netztrennung_stehen_drin(self):
        inhalt = self.datei("docker-compose.yml")
        for erwartet in (
            "read_only: true",
            "cap_drop",
            "no-new-privileges:true",
            "internal: true",
            "HTTPS_PROXY",
        ):
            self.assertIn(erwartet, inhalt, erwartet)
        # Der Runner haengt nur im internen Netz; nur der Proxy sieht beide.
        runner, egress = inhalt.split("  egress:", 1)
        self.assertNotIn("nightshift-extern", runner)
        self.assertIn("nightshift-extern", egress)

    def test_seatbelt_bleibt_als_option_erhalten(self):
        eintraege = helfer.zip_eintraege(self.zip_pfad)
        self.assertIn(PRAEFIX + "nightshift-sandbox.sb", eintraege)
        readme = self.datei("README-nightshift.md")
        self.assertIn("sandbox-exec -f nightshift-sandbox.sb", readme)
        # Die Variable darf nicht mehr als Weg in die Isolation dastehen.
        self.assertNotIn("NIGHTSHIFT_SANDBOXED=seatbelt", readme)

    def test_sandboxprofil_startet_ueberhaupt_ein_programm(self):
        """Ein Profil, unter dem nichts laeuft, schuetzt niemanden.

        Das Profil vor dieser Runde beendete schon /bin/echo mit SIGABRT,
        weil es Lesezugriffe ausserhalb weniger Pfade verbot und der
        dyld-Cache auf aktuellem macOS ausserhalb davon liegt.
        """
        if not sys.platform.startswith("darwin"):
            raise unittest.SkipTest("sandbox-exec gibt es nur auf macOS")
        if shutil.which("sandbox-exec") is None:
            raise unittest.SkipTest("sandbox-exec nicht vorhanden")
        arbeit = tempfile.mkdtemp(prefix="nightshift-sb-")
        try:
            profil = os.path.join(arbeit, "nightshift-sandbox.sb")
            with open(profil, "w") as datei:
                datei.write(self.datei("nightshift-sandbox.sb"))
            lauf = subprocess.run(
                ["sandbox-exec", "-f", profil, "/bin/echo", "start-ok"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            ausgabe = lauf.stdout.decode("utf-8", "replace")
            self.assertEqual(0, lauf.returncode, ausgabe)
            self.assertIn("start-ok", ausgabe)

            # Und die Sonde, an der der Runner die Isolation erkennt:
            # /Users muss unter dem Profil unlesbar sein.
            lauf = subprocess.run(
                ["sandbox-exec", "-f", profil, "/bin/ls", "/Users"],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            self.assertNotEqual(
                0, lauf.returncode,
                "unter dem Profil ist /Users lesbar, dann traegt die Sonde nicht",
            )
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_runner_bricht_ohne_isolation_ab_und_laeuft_mit_optout(self):
        """Der Kern der Umstellung: ohne Isolation kein Lauf.

        Ein Stub statt claude sorgt dafuer, dass kein echter API-Aufruf
        entsteht, egal welcher Zweig genommen wird.
        """
        if in_container():
            raise unittest.SkipTest(
                "dieser Test braucht eine Maschine ohne Container: "
                "hier misst der Runner zu Recht 'docker'"
            )
        arbeit = tempfile.mkdtemp(prefix="nightshift-lauf-")
        try:
            skript = os.path.join(arbeit, "nightshift-run.sh")
            with open(skript, "w") as datei:
                datei.write(
                    self.datei("nightshift-run.sh").replace(self.projekt, arbeit)
                )
            for name in ("nightshift-cost.sh", "nightshift-receipt.sh"):
                with open(os.path.join(arbeit, name), "w") as datei:
                    datei.write(self.datei(name))
            with open(os.path.join(arbeit, "runbook.md"), "w") as datei:
                datei.write(self.datei("runbook.md"))

            stubordner = os.path.join(arbeit, "bin")
            os.makedirs(stubordner)
            stub = os.path.join(stubordner, "claude")
            with open(stub, "w") as datei:
                datei.write("#!/bin/bash\necho '{\"type\":\"result\"}'\nexit 0\n")
            os.chmod(stub, 0o755)

            umgebung = dict(os.environ)
            umgebung["PATH"] = stubordner + os.pathsep + umgebung.get("PATH", "")
            umgebung["NIGHTSHIFT_PROJEKT"] = arbeit
            umgebung.pop("NIGHTSHIFT_SANDBOXED", None)
            umgebung.pop("NIGHTSHIFT_ALLOW_UNSANDBOXED", None)
            def starte(zusatz):
                eigene = dict(umgebung)
                eigene.update(zusatz)
                lauf = subprocess.run(
                    ["bash", skript],
                    cwd=arbeit,
                    env=eigene,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                return lauf.returncode, lauf.stdout.decode("utf-8", "replace")

            code, ausgabe = starte({})
            self.assertEqual(3, code, ausgabe)
            self.assertIn("nicht isoliert", ausgabe)

            code, ausgabe = starte({"NIGHTSHIFT_ALLOW_UNSANDBOXED": "1"})
            self.assertEqual(0, code, ausgabe)
            self.assertIn("der Lauf geht weiter", ausgabe)

            # Der Kern dieser Runde: die Variable schaltet nichts frei.
            # Frueher lief jeder Wert durch und landete unveraendert als
            # "isolation" im Receipt.
            for wert in ("banane", "seatbelt", "docker"):
                code, ausgabe = starte({"NIGHTSHIFT_SANDBOXED": wert})
                self.assertEqual(3, code, ausgabe)
                self.assertIn("gemessen wurde 'keine'", ausgabe)

            # Und beim bewussten Verzicht steht "keine" im Receipt, nicht
            # ein Wort, das jemand hingeschrieben hat.
            code, ausgabe = starte({"NIGHTSHIFT_ALLOW_UNSANDBOXED": "1"})
            self.assertEqual(0, code, ausgabe)
            self.assertIn("Isolation: keine", ausgabe)
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_compose_datei_ist_fuer_docker_compose_gueltig(self):
        kommando = compose_kommando()
        if kommando is None:
            raise unittest.SkipTest("kein docker compose erreichbar")
        arbeit = tempfile.mkdtemp(prefix="nightshift-compose-")
        try:
            for name in ("docker-compose.yml", "Dockerfile"):
                with open(os.path.join(arbeit, name), "w") as datei:
                    datei.write(self.datei(name))
            lauf = subprocess.run(
                kommando + ["-f", os.path.join(arbeit, "docker-compose.yml"), "config"],
                cwd=arbeit,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
            )
            ausgabe = lauf.stdout.decode("utf-8", "replace")
            self.assertEqual(0, lauf.returncode, ausgabe)
            self.assertIn("nightshift", ausgabe)
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
