#!/usr/bin/env python3
"""Übernimmt nur Paketnamen und Versionen aus der installierten Testumgebung."""

import json
import os
import re
import sys

MAX_OUTPUT_BYTES = 48 * 1024


def installed_packages(report):
    if report.get("version") != "1":
        raise ValueError("Unbekanntes pip-inspect-Format")
    installed = report.get("installed")
    if not isinstance(installed, list) or not 1 <= len(installed) <= 2000:
        raise ValueError("Die installierte Paketliste fehlt oder ist zu groß")
    packages = {}
    for item in installed:
        metadata = item["metadata"]
        name = metadata["name"]
        version = metadata["version"]
        if not isinstance(name, str) or not re.fullmatch(
            r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?", name
        ):
            raise ValueError("Ungültiger Paketname")
        name = re.sub(r"[-_.]+", "-", name).lower()
        if not isinstance(version, str) or not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9.!+_-]{0,127}", version
        ):
            raise ValueError("Ungültige installierte Paketversion")
        if name in packages:
            raise ValueError("Paket mehrfach in der Testumgebung vorhanden")
        packages[name] = version
    compact = json.dumps(sorted(packages.items()), separators=(",", ":"))
    if len(compact.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise ValueError("Paketliste überschreitet die Grenze für den Joboutput")
    return compact


if __name__ == "__main__":
    compact = installed_packages(json.load(sys.stdin))
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write("packages=" + compact + "\n")
