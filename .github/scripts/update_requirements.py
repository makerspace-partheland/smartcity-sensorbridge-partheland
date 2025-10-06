#!/usr/bin/env python3
"""
Update lower-bound versions in requirements files and Home Assistant manifest.

Rules:
- Only update to latest STABLE (non pre-release) version.
- Only apply patch/minor updates automatically. Major updates are skipped.
- Critical packages (homeassistant, paho-mqtt, aiohttp) are always limited to patch/minor.

Target files:
- requirements.txt
- requirements_test.txt
- custom_components/sensorbridge_partheland/manifest.json

Outputs:
- Modifies files in-place if updates are available.
- Prints a concise change summary to stdout.

No third-party dependencies required (stdlib only).
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple


CRITICAL_PACKAGES = {
    "homeassistant",
    "paho-mqtt",
    "aiohttp",
}

REQ_FILES = [
    "requirements.txt",
    "requirements_test.txt",
]

MANIFEST_PATH = "custom_components/sensorbridge_partheland/manifest.json"


PYTEST_HA_REQUIREMENTS_URL = "https://raw.githubusercontent.com/MatthewFlamm/pytest-homeassistant-custom-component/master/requirements_test.txt"
PYTEST_HA_DEPENDENT_PACKAGES: set[str] = set()

README_PATH = Path("README.md")
README_VERSION_PATTERN = re.compile(r"(Home Assistant \(Version\s*)([0-9][^)\s]*)(\s*oder neuer\))")
README_COMPAT_PATTERN = re.compile(r"(Zuletzt erfolgreich getestet mit Home Assistant )([0-9][^\.\s]*)(\.)")


@dataclass
class Requirement:
    original_line: str
    package: str
    extras: Optional[str]
    operator: str
    version: str
    marker: Optional[str]


REQ_LINE_RE = re.compile(
    r"^\s*"  # leading space
    r"(?P<package>[A-Za-z0-9_.\-]+)"  # package name
    r"(?P<extras>\[[^\]]+\])?"  # optional extras
    r"\s*(?P<op>>=|==)\s*"  # operator
    r"(?P<version>[0-9][^\s;#]*)"  # version (starts with digit)
    r"\s*(?:;\s*(?P<marker>.*))?$"  # optional environment marker
)


def parse_requirement_line(line: str) -> Optional[Requirement]:
    if not line.strip() or line.lstrip().startswith("#"):
        return None
    m = REQ_LINE_RE.match(line.rstrip())
    if not m:
        return None
    return Requirement(
        original_line=line,
        package=m.group("package"),
        extras=m.group("extras"),
        operator=m.group("op"),
        version=m.group("version"),
        marker=m.group("marker"),
    )


def numeric_tuple(version: str, width: int = 4) -> Tuple[int, ...]:
    parts = version.split(".")
    nums: List[int] = []
    for p in parts[:width]:
        m = re.match(r"(\d+)", p)
        nums.append(int(m.group(1)) if m else 0)
    while len(nums) < width:
        nums.append(0)
    return tuple(nums)


def is_stable_version(version: str) -> bool:
    v = version.lower()
    if any(tag in v for tag in ["a", "b", "rc", "dev", "pre", "alpha", "beta"]):
        # coarse filter, still allow digits with post/local tags by extra check below
        # if it includes such tags with digits only segments (rare), we'll still treat as pre-release
        return False
    # Allow post releases like 1.2.3.post1? We'll treat as stable by requiring start digits in each segment
    return True


def is_homeassistant_beta(version: str) -> bool:
    """Return True if the version string represents a Home Assistant beta build."""
    lowered = version.lower()
    if 'b' not in lowered:
        return False
    # treat beta markers like 'b' while allowing post/dev releases
    return not any(tag in lowered for tag in ('post', 'dev'))


def update_type(old: str, new: str) -> str:
    o = numeric_tuple(old)
    n = numeric_tuple(new)
    if n <= o:
        return "same"
    if n[0] > o[0]:
        return "major"
    if n[1] > o[1]:
        return "minor"
    return "patch"


def fetch_pytest_ha_requirements() -> Dict[str, str]:
    """Fetch and parse pytest-homeassistant-custom-component requirements."""
    global PYTEST_HA_DEPENDENT_PACKAGES

    try:
        with urllib.request.urlopen(PYTEST_HA_REQUIREMENTS_URL, timeout=20) as resp:
            content = resp.read().decode('utf-8')
    except Exception:
        return {}

    requirements: Dict[str, str] = {}
    PYTEST_HA_DEPENDENT_PACKAGES.clear()

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('-') or line.lower().startswith('r '):
            continue

        req = parse_requirement_line(line)
        if req:
            package_name = req.package.lower()
            PYTEST_HA_DEPENDENT_PACKAGES.add(package_name)
            requirements[package_name] = req.version

    return requirements


def fetch_latest_version(package: str) -> Optional[str]:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.load(resp)
    except Exception:
        return None

    releases: Dict[str, List[dict]] = data.get("releases", {})
    stable_versions = [v for v in releases.keys() if is_stable_version(v)]
    if not stable_versions:
        return None
    latest = max(stable_versions, key=numeric_tuple)
    return latest


def rebuild_line(req: Requirement, new_version: str) -> str:
    parts = [f"{req.package}"]
    if req.extras:
        parts.append(req.extras)
    parts.append(f" {req.operator} {new_version}")
    line = "".join(parts)
    if req.marker:
        line = f"{line}; {req.marker}"
    return line + "\n"


def process_requirements_file(path: str, changes: List[str], pytest_ha_reqs: Dict[str, str]) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        lines = fh.readlines()

    updated_lines: List[str] = []
    file_changed = False

    for line in lines:
        req = parse_requirement_line(line)
        if not req:
            updated_lines.append(line)
            continue

        pkg_name = req.package.lower()
        base_pkg = pkg_name  # extras already separated

        if base_pkg in PYTEST_HA_DEPENDENT_PACKAGES and base_pkg in pytest_ha_reqs:
            target_version = pytest_ha_reqs[base_pkg]

            if base_pkg == 'homeassistant' and is_homeassistant_beta(target_version):
                updated_lines.append(line)
                changes.append(f"{path}: {req.package} {req.operator}{req.version} -> {req.operator}{target_version} (SKIPPED - beta version)")
                continue

            utype = update_type(req.version, target_version)

            if utype in ('patch', 'minor') and numeric_tuple(target_version) >= numeric_tuple(req.version):
                new_line = rebuild_line(req, target_version)
                if new_line != line:
                    updated_lines.append(new_line)
                    file_changed = True
                    changes.append(f"{path}: {req.package} {req.operator}{req.version} -> {req.operator}{target_version} (from pytest-homeassistant-custom-component)")
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
            continue

        latest = fetch_latest_version(base_pkg)
        if not latest:
            updated_lines.append(line)
            continue

        utype = update_type(req.version, latest)
        if utype == "same":
            updated_lines.append(line)
            continue

        # Only patch/minor updates auto-applied
        if utype == "major":
            updated_lines.append(line)
            continue

        # Critical packages are never auto-updated to major (already filtered above)
        # For others, still limit to patch/minor per policy

        new_line = rebuild_line(req, latest)
        if new_line != line:
            updated_lines.append(new_line)
            file_changed = True
            changes.append(f"{path}: {req.package} {req.operator}{req.version} -> {req.operator}{latest}")
        else:
            updated_lines.append(line)

    if file_changed:
        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(updated_lines)


REQ_MANIFEST_RE = re.compile(
    r"^(?P<name>[A-Za-z0-9_.\-]+)"  # package
    r"(?P<extras>\[[^\]]+\])?"  # extras
    r"(?P<op>>=|==)"  # operator
    r"(?P<version>[0-9][^\s;#]*)$"  # version
)



def extract_homeassistant_version(path: str) -> Optional[str]:
    """Return the noted Home Assistant version from the given requirements file."""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            req = parse_requirement_line(line)
            if req and req.package == "homeassistant":
                return req.version.strip()
    return None


def update_readme(homeassistant_version: Optional[str], changes: List[str]) -> None:
    """Update README with the documented Home Assistant compatibility version."""
    if not homeassistant_version or not README_PATH.exists():
        return

    text = README_PATH.read_text(encoding="utf-8")
    updated = False

    def _replace_version(match: re.Match[str]) -> str:
        return f"{match.group(1)}{homeassistant_version}{match.group(3)}"

    new_text, count = README_VERSION_PATTERN.subn(_replace_version, text, count=1)
    if count:
        text = new_text
        updated = True

    compat_line = f"Zuletzt erfolgreich getestet mit Home Assistant {homeassistant_version}."

    def _replace_compat(_: re.Match[str]) -> str:
        return compat_line

    new_text, count = README_COMPAT_PATTERN.subn(_replace_compat, text, count=1)
    if count:
        text = new_text
        updated = True
    else:
        marker = (
            "Die Integration wird durch die Automatisierung eigenständig gepflegt und "
            "führt erfolgreiche Abhängigkeits-PRs nach bestandenem CI- und "
            "HA-Kompatibilitätscheck automatisch zusammen."
        )
        if marker in text and compat_line not in text:
            text = text.replace(marker, f"{marker} {compat_line}", 1)
            updated = True
        elif compat_line not in text:
            updates_heading = "## Updates\n\n"
            if updates_heading in text:
                text = text.replace(updates_heading, f"{updates_heading}{compat_line}\n\n", 1)
                updated = True

    if updated:
        README_PATH.write_text(text, encoding="utf-8")
        changes.append(
            f"README.md: Dokumentierte Home Assistant Version auf {homeassistant_version} aktualisiert"
        )


def process_manifest(path: str, changes: List[str]) -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)

    reqs = data.get("requirements", [])
    if not isinstance(reqs, list):
        return

    updated = False
    new_reqs: List[str] = []
    for entry in reqs:
        if not isinstance(entry, str):
            new_reqs.append(entry)
            continue
        m = REQ_MANIFEST_RE.match(entry.strip())
        if not m:
            new_reqs.append(entry)
            continue
        package = m.group("name")
        extras = m.group("extras") or ""
        op = m.group("op")
        ver = m.group("version")

        latest = fetch_latest_version(package)
        if not latest:
            new_reqs.append(entry)
            continue
        utype = update_type(ver, latest)
        if utype in ("patch", "minor"):
            # Critical packages: still allow patch/minor only (already enforced)
            new_entry = f"{package}{extras}{op}{latest}"
            if new_entry != entry:
                updated = True
                new_reqs.append(new_entry)
                changes.append(f"{path}: {package} {op}{ver} -> {op}{latest}")
            else:
                new_reqs.append(entry)
        else:
            # major or same
            new_reqs.append(entry)

    if updated:
        data["requirements"] = new_reqs
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")


def main() -> int:
    changes: List[str] = []

    print('Fetching pytest-homeassistant-custom-component requirements...')
    pytest_ha_reqs = fetch_pytest_ha_requirements()
    if pytest_ha_reqs:
        print(f"Loaded {len(pytest_ha_reqs)} requirements from pytest-homeassistant-custom-component")
        print(f"Tracking {len(PYTEST_HA_DEPENDENT_PACKAGES)} packages for dependency alignment")
    else:
        print('Warning: Could not fetch pytest-homeassistant-custom-component requirements')

    for path in REQ_FILES:
        process_requirements_file(path, changes, pytest_ha_reqs)
    process_manifest(MANIFEST_PATH, changes)

    ha_version = extract_homeassistant_version('requirements_test.txt')
    if ha_version is None:
        ha_version = extract_homeassistant_version('requirements.txt')
    update_readme(ha_version, changes)

    if changes:
        print("Dependency updates applied:")
        for c in changes:
            print(f"- {c}")
        return 0
    else:
        print("No dependency updates available (patch/minor).")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())


