"""Prueft das Release-Artefakt, bevor jemand ein Tag setzt.

Ein Release-Workflow laesst sich erst pruefen, wenn ein Tag da ist, und dann
ist es zu spaet. Deshalb baut dieser Test bei jedem Push dieselben Archive,
die der Workflow spaeter an das Release haengt, und schaut hinein.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

import helfer

SKRIPT = os.path.join(helfer.REPO, "scripts", "build_release.py")

# Was in den Archiven stehen muss, Eintrag fuer Eintrag.
ARTEFAKTE = {
    "nightshift.skill": {
        "nightshift/LICENSE",
        "nightshift/SKILL.md",
        "nightshift/VERSION",
        "nightshift/scripts/build_zip.py",
    },
    "24x7.skill": {
        "24x7/LICENSE",
        "24x7/SKILL.md",
        "24x7/VERSION",
        "24x7/scripts/build_zip.py",
    },
}

# Repo-Innereien, die niemals mitgeliefert werden duerfen. Geprueft wird auf
# Teilstrings, damit auch .gitignore oder eine .pyc auffaellt.
VERBOTEN = (
    ".git",
    ".github",
    "index.html",
    "course.html",
    "-guide_",
    "__pycache__",
    ".pyc",
    ".DS_Store",
    "tests/",
    "workflows",
)

# Dateien, die einen Installationsweg beschreiben.
DOKUMENTE = (
    "README.md",
    "index.html",
    "nightshift-guide_de.md",
    "nightshift-guide_en.md",
    "24x7-guide_de.md",
    "24x7-guide_en.md",
)

# Faengt sowohl releases/latest/download/<name> als auch
# releases/download/<tag>/<name>.
URL_MUSTER = re.compile(r"releases/(?:latest/download|download/[^/\s]+)/([A-Za-z0-9._-]+)")

VERSION_MUSTER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def baue(zielordner):
    """Ruft das Packaging-Skript auf und gibt seine Ausgabe zurueck."""
    lauf = subprocess.run(
        [sys.executable, SKRIPT, zielordner],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    ausgabe = lauf.stdout.decode("utf-8", "replace")
    if lauf.returncode != 0:
        raise AssertionError(
            "build_release.py beendet mit Exit-Code %d:\n%s"
            % (lauf.returncode, ausgabe)
        )
    return ausgabe


def pruefsumme(pfad):
    with open(pfad, "rb") as datei:
        return hashlib.sha256(datei.read()).hexdigest()


def repo_datei(name):
    with open(os.path.join(helfer.REPO, name), "r") as datei:
        return datei.read()


class PaketTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ordner = tempfile.mkdtemp(prefix="nightshift-paket-")
        cls.ausgabe = baue(cls.ordner)
        cls.version = repo_datei("VERSION").strip()

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.ordner, ignore_errors=True)

    def pfad(self, artefakt):
        return os.path.join(self.ordner, artefakt)

    def test_beide_artefakte_existieren_und_sind_nicht_leer(self):
        for artefakt in ARTEFAKTE:
            pfad = self.pfad(artefakt)
            self.assertTrue(os.path.isfile(pfad), "fehlt: %s" % artefakt)
            self.assertGreater(os.path.getsize(pfad), 0, "leer: %s" % artefakt)

    def test_artefakte_enthalten_genau_die_erwarteten_dateien(self):
        for artefakt, erwartet in ARTEFAKTE.items():
            self.assertEqual(
                erwartet,
                set(helfer.zip_eintraege(self.pfad(artefakt))),
                "Inhalt von %s" % artefakt,
            )

    def test_artefakte_enthalten_keine_repo_innereien(self):
        for artefakt in ARTEFAKTE:
            for eintrag in helfer.zip_eintraege(self.pfad(artefakt)):
                for verboten in VERBOTEN:
                    self.assertNotIn(
                        verboten,
                        eintrag,
                        "%s: %r enthaelt %r" % (artefakt, eintrag, verboten),
                    )
                self.assertFalse(
                    eintrag.startswith("/") or ".." in eintrag.split("/"),
                    "%s: unsauberer Pfad %r" % (artefakt, eintrag),
                )

    def test_archiv_legt_den_skill_direkt_unter_seinen_namen(self):
        # unzip -d ~/.claude/skills muss ~/.claude/skills/<name>/SKILL.md
        # ergeben, sonst findet Claude den Skill nicht.
        for artefakt in ARTEFAKTE:
            skill = artefakt[: -len(".skill")]
            eintraege = helfer.zip_eintraege(self.pfad(artefakt))
            for eintrag in eintraege:
                self.assertTrue(
                    eintrag.startswith(skill + "/"),
                    "%s: %r liegt nicht unter %s/" % (artefakt, eintrag, skill),
                )
            kopf = helfer.datei_aus_zip(self.pfad(artefakt), skill + "/SKILL.md")
            self.assertTrue(kopf.startswith("---\nname: %s\n" % skill), kopf[:60])

    def test_zwei_laeufe_ergeben_byteweise_dasselbe_archiv(self):
        zweiter = tempfile.mkdtemp(prefix="nightshift-paket-zwei-")
        try:
            baue(zweiter)
            for artefakt in ARTEFAKTE:
                self.assertEqual(
                    pruefsumme(self.pfad(artefakt)),
                    pruefsumme(os.path.join(zweiter, artefakt)),
                    "%s ist nicht reproduzierbar" % artefakt,
                )
        finally:
            shutil.rmtree(zweiter, ignore_errors=True)

    def test_eintraege_tragen_einen_festen_zeitstempel(self):
        for artefakt in ARTEFAKTE:
            with zipfile.ZipFile(self.pfad(artefakt)) as archiv:
                for info in archiv.infolist():
                    self.assertEqual(
                        (1980, 1, 1, 0, 0, 0),
                        info.date_time,
                        "%s: %s traegt eine Uhrzeit" % (artefakt, info.filename),
                    )

    def test_version_steht_nur_in_der_versionsdatei_und_wird_gelesen(self):
        self.assertTrue(
            VERSION_MUSTER.match(self.version),
            "VERSION enthaelt %r" % self.version,
        )
        for artefakt in ARTEFAKTE:
            skill = artefakt[: -len(".skill")]
            im_archiv = helfer.datei_aus_zip(
                self.pfad(artefakt), skill + "/VERSION"
            ).strip()
            self.assertEqual(self.version, im_archiv, artefakt)

    def test_changelog_hat_einen_eintrag_fuer_die_version(self):
        changelog = repo_datei("CHANGELOG.md")
        self.assertIn(
            "## [%s]" % self.version,
            changelog,
            "CHANGELOG.md hat keinen Abschnitt fuer %s" % self.version,
        )

    def test_landingpage_nennt_dieselbe_version(self):
        self.assertIn("v%s" % self.version, repo_datei("index.html"))

    def test_dokumentierte_download_urls_treffen_die_artefaktnamen(self):
        gefunden = set()
        for name in DOKUMENTE:
            for treffer in URL_MUSTER.findall(repo_datei(name)):
                gefunden.add(treffer)
                self.assertIn(
                    treffer,
                    ARTEFAKTE,
                    "%s verweist auf %r, das Skript baut das nicht" % (name, treffer),
                )
        self.assertEqual(
            set(ARTEFAKTE),
            gefunden,
            "nicht jedes Artefakt ist in der Doku verlinkt",
        )

    def test_skript_meldet_die_pruefsummen(self):
        for artefakt in ARTEFAKTE:
            self.assertIn(pruefsumme(self.pfad(artefakt)), self.ausgabe)


if __name__ == "__main__":
    unittest.main()
