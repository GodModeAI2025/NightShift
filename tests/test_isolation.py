"""Prueft die Container-Isolation, die beide Generatoren erzeugen.

Zwei Ebenen. Statisch: enthaelt das Setup Dockerfile und docker-compose.yml,
mountet die Compose-Datei genau einen Hostpfad, und weigert sich der Runner
ohne Isolation zu starten. Dynamisch: laesst 'docker compose config' die
erzeugte Datei pruefen, sobald ein Compose-Kommando erreichbar ist.

Seit Welle 7 gilt beides fuer beide Skills. Die Vorlagen stehen einmal in
gemeinsam.py, die Tabelle SKILLS unten haelt fest, welche Namen jeder Skill
einsetzt, und die strukturellen Tests laufen ueber beide.

Der Lauf im Container selbst gehoert nicht hierher: er braucht ein Netz, ein
Basis-Image und mehrere Minuten Bauzeit. Der Nachweis dafuer steht im
Pull-Request.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest

import helfer

PRAEFIX = "nightshift-setup/"

# Was jeder Skill in dieselben Vorlagen einsetzt.
SKILLS = {
    "nightshift": {
        "praefix": "nightshift-setup/",
        "dienst": "nightshift",
        "mount": "/project",
        "dockerskript": "nightshift-docker.sh",
        "startskript": "nightshift-run.sh",
        "profil": "nightshift-sandbox.sb",
        "sandboxvar": "NIGHTSHIFT_SANDBOXED",
        "pfadvar": "NIGHTSHIFT_PROJEKT",
        "pfad_env": "NIGHTSHIFT_PROJECT",
        "readme": "README-nightshift.md",
    },
    "24x7": {
        "praefix": "24x7-setup/",
        "dienst": "24x7",
        "mount": "/workspace",
        "dockerskript": "24x7-docker.sh",
        "startskript": "runner.sh",
        "profil": "sandbox.sb",
        "sandboxvar": "CLAUDE_24X7_SANDBOXED",
        "pfadvar": "CLAUDE_24X7_WORKSPACE",
        "pfad_env": "CLAUDE_24X7_WORKSPACE",
        "readme": "README.md",
    },
}


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
        cls.zips = {
            name: helfer.baue_zip(name, cls.ordner) for name in SKILLS
        }
        cls.zip_pfad = cls.zips["nightshift"]
        cls.projekt = helfer.GENERATOREN["nightshift"]["env"]["NIGHTSHIFT_PROJECT"]
        cls.wurzeln = {
            name: helfer.GENERATOREN[name]["env"][konfig["pfad_env"]]
            for name, konfig in SKILLS.items()
        }

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def datei(self, name):
        return helfer.datei_aus_zip(self.zip_pfad, PRAEFIX + name)

    def skilldatei(self, skill, name):
        return helfer.datei_aus_zip(
            self.zips[skill], SKILLS[skill]["praefix"] + name
        )

    def test_setup_enthaelt_dockerfile_und_compose(self):
        for skill, konfig in SKILLS.items():
            eintraege = helfer.zip_eintraege(self.zips[skill])
            praefix = konfig["praefix"]
            for name in ("Dockerfile", "docker-compose.yml", konfig["dockerskript"]):
                self.assertIn(praefix + name, eintraege, skill)

    def test_dockerfile_hat_beide_ziele_und_laeuft_nicht_als_root(self):
        for skill, konfig in SKILLS.items():
            inhalt = self.skilldatei(skill, "Dockerfile")
            self.assertIn("AS runner", inhalt, skill)
            self.assertIn("AS egress", inhalt, skill)
            self.assertIn("USER node", inhalt, skill)
            self.assertIn("USER tinyproxy", inhalt, skill)
            # Die Variable ist im Container nur noch die Gegenprobe: der
            # Runner misst selbst und bricht ab, wenn sie etwas anderes
            # behauptet. Der Pfad im Container ist ein anderer als auf dem
            # Host, und die Pfadvariable haelt ihn beweglich.
            self.assertIn("%s=docker" % konfig["sandboxvar"], inhalt, skill)
            self.assertIn(
                "%s=%s" % (konfig["pfadvar"], konfig["mount"]), inhalt, skill
            )

    def test_compose_mountet_nur_den_einen_hostpfad(self):
        for skill, konfig in SKILLS.items():
            inhalt = self.skilldatei(skill, "docker-compose.yml")
            wurzel = self.wurzeln[skill]
            mounts = [
                zeile.strip().strip('-').strip().strip('"')
                for zeile in inhalt.splitlines()
                if zeile.strip().startswith('- "') and ":/" in zeile
            ]
            self.assertIn("%s:%s" % (wurzel, konfig["mount"]), mounts, skill)
            for mount in mounts:
                quelle = mount.split(":")[0]
                # Alles andere muss ein benanntes Volume sein, also ohne
                # Schraegstrich. Ein zweiter Hostpfad waere ein Loch.
                if quelle != wurzel:
                    self.assertNotIn(
                        "/", quelle, "%s: zweiter Hostpfad im Mount: %s" % (skill, mount)
                    )

    def test_compose_haerten_und_netztrennung_stehen_drin(self):
        for skill, konfig in SKILLS.items():
            inhalt = self.skilldatei(skill, "docker-compose.yml")
            for erwartet in (
                "read_only: true",
                "cap_drop",
                "no-new-privileges:true",
                "internal: true",
                "HTTPS_PROXY",
            ):
                self.assertIn(erwartet, inhalt, "%s: %s" % (skill, erwartet))
            # Der Runner haengt nur im internen Netz; nur der Proxy sieht beide.
            aussennetz = konfig["dienst"] + "-extern"
            runner, egress = inhalt.split("  egress:", 1)
            self.assertNotIn(aussennetz, runner, skill)
            self.assertIn(aussennetz, egress, skill)

    def test_compose_startet_das_startskript_aus_dem_gemounteten_pfad(self):
        # Der Runner liegt im Setup, das Setup liegt im gemounteten Ordner.
        # Zeigt das Kommando woandershin, startet der Container nichts.
        for skill, konfig in SKILLS.items():
            inhalt = self.skilldatei(skill, "docker-compose.yml")
            self.assertIn(
                '["bash", "%s/%s"]' % (konfig["mount"], konfig["startskript"]),
                inhalt,
                skill,
            )

    def test_seatbelt_bleibt_als_option_erhalten(self):
        for skill, konfig in SKILLS.items():
            eintraege = helfer.zip_eintraege(self.zips[skill])
            self.assertIn(konfig["praefix"] + konfig["profil"], eintraege, skill)
            readme = self.skilldatei(skill, konfig["readme"])
            self.assertIn(
                "sandbox-exec -f %s" % konfig["profil"], readme, skill
            )
            # Die Variable darf nicht als Weg in die Isolation dastehen.
            self.assertNotIn("%s=seatbelt" % konfig["sandboxvar"], readme, skill)

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
            for skill, konfig in SKILLS.items():
                profil = os.path.join(arbeit, konfig["profil"])
                with open(profil, "w") as datei:
                    datei.write(self.skilldatei(skill, konfig["profil"]))
                lauf = subprocess.run(
                    ["sandbox-exec", "-f", profil, "/bin/echo", "start-ok"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                ausgabe = lauf.stdout.decode("utf-8", "replace")
                self.assertEqual(0, lauf.returncode, "%s: %s" % (skill, ausgabe))
                self.assertIn("start-ok", ausgabe, skill)

                # Und die Sonde, an der der Runner die Isolation erkennt:
                # /Users muss unter dem Profil unlesbar sein.
                lauf = subprocess.run(
                    ["sandbox-exec", "-f", profil, "/bin/ls", "/Users"],
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                )
                self.assertNotEqual(
                    0, lauf.returncode,
                    "%s: unter dem Profil ist /Users lesbar, dann traegt die "
                    "Sonde nicht" % skill,
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

    def test_24x7_runner_bricht_ohne_isolation_ab_und_laeuft_mit_optout(self):
        """Dieselbe Schranke wie bei Nightshift, jetzt auch fuer den Daemon.

        Der Runner laeuft endlos, die Pruefung steht aber vor der Schleife.
        Der Abbruchfall ist deshalb direkt messbar; fuer den Opt-out-Fall
        startet der Test den Runner im Hintergrund, wartet auf das Banner und
        beendet ihn wieder. Ein claude-Stub sorgt dafuer, dass in keinem Zweig
        ein API-Aufruf entsteht.
        """
        if in_container():
            raise unittest.SkipTest(
                "dieser Test braucht eine Maschine ohne Container: "
                "hier misst der Runner zu Recht 'docker'"
            )
        if shutil.which("timeout") is None and shutil.which("gtimeout") is None:
            raise unittest.SkipTest(
                "der Runner bricht ohne timeout schon vor der Isolationspruefung ab"
            )
        arbeit = tempfile.mkdtemp(prefix="24x7-lauf-")
        try:
            for name in ("runner.sh", "sandbox.sb"):
                with open(os.path.join(arbeit, name), "w") as datei:
                    datei.write(self.skilldatei("24x7", name))
            os.makedirs(os.path.join(arbeit, "idle"))
            with open(os.path.join(arbeit, "idle", "idle-tasks.md"), "w") as datei:
                datei.write(self.skilldatei("24x7", "idle/idle-tasks.md"))

            stubordner = os.path.join(arbeit, "bin")
            os.makedirs(stubordner)
            stub = os.path.join(stubordner, "claude")
            with open(stub, "w") as datei:
                datei.write("#!/bin/bash\necho '{\"type\":\"result\"}'\nexit 0\n")
            os.chmod(stub, 0o755)

            umgebung = dict(os.environ)
            umgebung["PATH"] = stubordner + os.pathsep + umgebung.get("PATH", "")
            umgebung["CLAUDE_24X7_WORKSPACE"] = arbeit
            umgebung.pop("CLAUDE_24X7_SANDBOXED", None)
            umgebung.pop("CLAUDE_24X7_ALLOW_UNSANDBOXED", None)
            skript = os.path.join(arbeit, "runner.sh")

            def starte(zusatz):
                # Die PID-Datei liegt fest unter /tmp; ein Rest aus einem
                # frueheren Lauf wuerde den Start mit Exit 1 abweisen.
                if os.path.exists("/tmp/24x7.pid"):
                    os.remove("/tmp/24x7.pid")
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

            # Die Variable schaltet nichts frei, sie wird geprueft.
            for wert in ("banane", "seatbelt", "docker"):
                code, ausgabe = starte({"CLAUDE_24X7_SANDBOXED": wert})
                self.assertEqual(3, code, ausgabe)
                self.assertIn("gemessen wurde 'keine'", ausgabe)

            # Bewusster Verzicht: der Runner startet und nennt den Zustand.
            if os.path.exists("/tmp/24x7.pid"):
                os.remove("/tmp/24x7.pid")
            eigene = dict(umgebung)
            eigene["CLAUDE_24X7_ALLOW_UNSANDBOXED"] = "1"
            protokoll = os.path.join(arbeit, "lauf.log")
            with open(protokoll, "w") as datei:
                lauf = subprocess.Popen(
                    ["bash", skript],
                    cwd=arbeit,
                    env=eigene,
                    stdout=datei,
                    stderr=subprocess.STDOUT,
                )
            try:
                inhalt = ""
                for _ in range(120):
                    time.sleep(0.25)
                    with open(protokoll) as datei:
                        inhalt = datei.read()
                    if "Isolation: keine" in inhalt:
                        break
                self.assertIn("ist gesetzt, der Lauf geht weiter", inhalt)
                self.assertIn("Isolation: keine", inhalt)
            finally:
                lauf.terminate()
                lauf.wait()
                if os.path.exists("/tmp/24x7.pid"):
                    os.remove("/tmp/24x7.pid")
        finally:
            shutil.rmtree(arbeit, ignore_errors=True)

    def test_compose_datei_ist_fuer_docker_compose_gueltig(self):
        kommando = compose_kommando()
        if kommando is None:
            raise unittest.SkipTest("kein docker compose erreichbar")
        for skill, konfig in SKILLS.items():
            arbeit = tempfile.mkdtemp(prefix="nightshift-compose-")
            try:
                for name in ("docker-compose.yml", "Dockerfile"):
                    with open(os.path.join(arbeit, name), "w") as datei:
                        datei.write(self.skilldatei(skill, name))
                lauf = subprocess.run(
                    kommando
                    + ["-f", os.path.join(arbeit, "docker-compose.yml"), "config"],
                    cwd=arbeit,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                )
                ausgabe = lauf.stdout.decode("utf-8", "replace")
                self.assertEqual(0, lauf.returncode, "%s: %s" % (skill, ausgabe))
                self.assertIn(konfig["dienst"], ausgabe, skill)
            finally:
                shutil.rmtree(arbeit, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
