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
        # Der Runner muss wissen, dass er isoliert laeuft, und das Projekt im
        # Container unter /project finden statt unter dem Pfad des Hosts.
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
        self.assertIn("sandbox-exec", readme)
        self.assertIn("NIGHTSHIFT_SANDBOXED=seatbelt", readme)

    def test_runner_bricht_ohne_isolation_ab_und_laeuft_mit_optout(self):
        """Der Kern der Umstellung: ohne Isolation kein Lauf.

        Ein Stub statt claude sorgt dafuer, dass kein echter API-Aufruf
        entsteht, egal welcher Zweig genommen wird.
        """
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

            code, ausgabe = starte({"NIGHTSHIFT_SANDBOXED": "docker"})
            self.assertEqual(0, code, ausgabe)
            self.assertIn("Isolation: docker", ausgabe)
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
