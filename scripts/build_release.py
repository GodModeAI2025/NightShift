#!/usr/bin/env python3
"""Packt die beiden Skills als Release-Artefakte.

    python3 scripts/build_release.py <ausgabeordner>

Erzeugt <ausgabeordner>/nightshift.skill und <ausgabeordner>/24x7.skill. Das
sind ZIP-Archive; die Endung .skill ist die, die README und Landingpage seit
jeher nennen, und der dort dokumentierte Befehl

    unzip nightshift.skill -d ~/.claude/skills/

legt den Skill an genau die Stelle, die SKILL.md und die vier Guides nennen.
Jedes Archiv enthaelt dafuer genau einen Ordner, der so heisst wie der Skill.

Nicht zu verwechseln mit nightshift/scripts/build_zip.py und
24x7/scripts/build_zip.py: die bauen ein Setup fuer ein konkretes Projekt des
Nutzers. Dieses Skript hier baut den Skill selbst.

Laeuft ohne Netz, ohne git, ohne GitHub und nur mit der Standardbibliothek,
damit dasselbe lokal und in der CI passiert. Python 3.9 ist die Untergrenze,
das ist das System-Python von macOS.

Zwei Laeufe hintereinander liefern byteweise dasselbe Archiv: die Dateiliste
ist fest verdrahtet und sortiert, jeder Eintrag bekommt einen festen
Zeitstempel und feste Rechte, und es landet nichts im Archiv, was nicht
namentlich aufgezaehlt ist.
"""

import hashlib
import os
import re
import sys
import zipfile

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VERSIONSDATEI = os.path.join(REPO, "VERSION")

# Fester Zeitstempel fuer jeden Eintrag. 1980-01-01 00:00:00 ist die
# frueheste Zeit, die das ZIP-Format darstellen kann.
ZEITSTEMPEL = (1980, 1, 1, 0, 0, 0)

# Feste Rechte fuer jeden Eintrag: regulaere Datei, 0644. Alle Quelldateien
# stehen so im Index (git ls-files -s), keine ist ausfuehrbar.
RECHTE = (0o100644 << 16)

# create_system 3 heisst Unix. Ohne das Setzen schreibt zipfile den Wert der
# Plattform hinein, und ein Lauf unter Windows ergaebe ein anderes Archiv.
UNIX = 3

# Was in welches Archiv gehoert. Links der Pfad im Repo, rechts der Pfad im
# Archiv. Eine Allowlist, keine Filterliste: was hier nicht steht, kann nicht
# ins Artefakt geraten, auch kein __pycache__, kein .git, kein index.html.
SKILLS = {
    "nightshift": {
        "artefakt": "nightshift.skill",
        "dateien": [
            ("LICENSE", "nightshift/LICENSE"),
            ("nightshift/SKILL.md", "nightshift/SKILL.md"),
            ("nightshift/scripts/build_zip.py", "nightshift/scripts/build_zip.py"),
        ],
    },
    "24x7": {
        "artefakt": "24x7.skill",
        "dateien": [
            ("LICENSE", "24x7/LICENSE"),
            ("24x7/SKILL.md", "24x7/SKILL.md"),
            ("24x7/scripts/build_zip.py", "24x7/scripts/build_zip.py"),
        ],
    },
}

# Zusaetzlich bekommt jeder Skill eine VERSION-Datei aus der Versionsquelle,
# damit man einer Installation unter ~/.claude/skills/ ansehen kann, welches
# Release sie ist.
VERSIONSEINTRAG = "%s/VERSION"


def version_lesen():
    """Liest die Versionsquelle und prueft ihr Format."""
    if not os.path.isfile(VERSIONSDATEI):
        raise SystemExit("VERSION fehlt: %s" % VERSIONSDATEI)
    with open(VERSIONSDATEI, "r") as datei:
        version = datei.read().strip()
    if not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", version):
        raise SystemExit(
            "VERSION enthaelt %r, erwartet wird MAJOR.MINOR.PATCH" % version
        )
    return version


def eintrag_schreiben(archiv, name, daten):
    """Schreibt einen Eintrag mit festem Zeitstempel und festen Rechten."""
    info = zipfile.ZipInfo(name, date_time=ZEITSTEMPEL)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = RECHTE
    info.create_system = UNIX
    archiv.writestr(info, daten)


def artefakt_bauen(skill, ausgabeordner, version):
    """Baut ein Archiv und gibt (pfad, sha256) zurueck."""
    konfig = SKILLS[skill]
    ziel = os.path.join(ausgabeordner, konfig["artefakt"])

    eintraege = []
    for quelle, name in konfig["dateien"]:
        pfad = os.path.join(REPO, quelle)
        if not os.path.isfile(pfad):
            raise SystemExit("Quelldatei fehlt: %s" % pfad)
        with open(pfad, "rb") as datei:
            eintraege.append((name, datei.read()))
    eintraege.append(
        (VERSIONSEINTRAG % skill, (version + "\n").encode("utf-8"))
    )

    # Sortiert, damit die Reihenfolge im Archiv nicht davon abhaengt, in
    # welcher Reihenfolge die Liste oben gepflegt wird.
    eintraege.sort(key=lambda paar: paar[0])

    with zipfile.ZipFile(ziel, "w", zipfile.ZIP_DEFLATED) as archiv:
        for name, daten in eintraege:
            eintrag_schreiben(archiv, name, daten)

    with open(ziel, "rb") as datei:
        pruefsumme = hashlib.sha256(datei.read()).hexdigest()
    return ziel, pruefsumme


def main(argumente):
    if len(argumente) != 1:
        raise SystemExit(
            "Aufruf: python3 scripts/build_release.py <ausgabeordner>"
        )
    ausgabeordner = os.path.abspath(argumente[0])
    if not os.path.isdir(ausgabeordner):
        os.makedirs(ausgabeordner)

    version = version_lesen()
    print("Version %s" % version)
    for skill in sorted(SKILLS):
        ziel, pruefsumme = artefakt_bauen(skill, ausgabeordner, version)
        print(
            "%s  %d Bytes  sha256:%s"
            % (ziel, os.path.getsize(ziel), pruefsumme)
        )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
