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
import argparse
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
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
MIN_RELEASE_AGE_DAYS = 7


PYTEST_HA_PACKAGE = "pytest-homeassistant-custom-component"
PYTEST_HA_DEPENDENT_PACKAGES: set[str] = set()

README_PATH = Path("README.md")
README_VERSION_PATTERN = re.compile(
    r"(Home Assistant\s+)([0-9]+(?:\.[0-9]+)*)(\s+oder neuer)"
)
README_PYTHON_PATTERN = re.compile(
    r"(Python\s+)([0-9]+(?:\.[0-9]+)*)(\s+oder neuer)"
)
README_COMPAT_PATTERN = re.compile(
    r"(Zuletzt erfolgreich getestet mit Home Assistant )([0-9]+(?:\.[0-9]+)*)(\.)$",
    re.MULTILINE,
)


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


def fetch_package_info(package: str, version: str) -> dict:
    """Read dependency metadata for one published release without executing it."""
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    with urllib.request.urlopen(url, timeout=20) as resp:
        return json.load(resp)["info"]


def fetch_pytest_ha_requirements(version: str) -> Dict[str, str]:
    """Read requirements belonging to the selected, age-eligible PHACC release."""
    PYTEST_HA_DEPENDENT_PACKAGES.clear()
    info = fetch_package_info(PYTEST_HA_PACKAGE, version)

    requirements: Dict[str, str] = {}
    for line in info.get("requires_dist") or []:
        req = parse_requirement_line(line)
        if req:
            package_name = req.package.lower()
            PYTEST_HA_DEPENDENT_PACKAGES.add(package_name)
            requirements[package_name] = req.version

    return requirements


def fetch_pytest_ha_version() -> Optional[str]:
    """Select the newest stable PHACC release that meets the minimum age."""
    return fetch_latest_version(PYTEST_HA_PACKAGE)


def eligible_stable_versions(
    releases: Dict[str, List[dict]], now: Optional[datetime] = None
) -> List[str]:
    """Return stable versions whose published files are at least seven days old."""
    reference_time = now or datetime.now(timezone.utc)
    cutoff = reference_time - timedelta(days=MIN_RELEASE_AGE_DAYS)
    eligible: List[str] = []

    for version, files in releases.items():
        if not is_stable_version(version):
            continue

        upload_times: List[datetime] = []
        for release_file in files:
            if release_file.get("yanked"):
                continue
            timestamp = release_file.get("upload_time_iso_8601")
            if not timestamp:
                continue
            upload_times.append(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))

        if upload_times and max(upload_times) <= cutoff:
            eligible.append(version)

    return eligible


def fetch_package_releases(package: str) -> Optional[Dict[str, List[dict]]]:
    url = f"https://pypi.org/pypi/{package}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.load(resp)
    except Exception:
        return None

    return data.get("releases", {})


def release_is_eligible(package: str, version: str) -> bool:
    releases = fetch_package_releases(package)
    if releases is None:
        return False
    return version in eligible_stable_versions(releases)


def fetch_latest_version(package: str) -> Optional[str]:
    releases = fetch_package_releases(package)
    if releases is None:
        return None

    stable_versions = eligible_stable_versions(releases)
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


def process_requirements_file(
    path: str,
    changes: List[str],
    pytest_ha_reqs: Dict[str, str],
    pytest_ha_version: Optional[str],
) -> None:
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

        if base_pkg == "pytest-homeassistant-custom-component" and pytest_ha_version:
            target_version = pytest_ha_version

            if target_version == req.version:
                updated_lines.append(line)
            elif numeric_tuple(target_version) >= numeric_tuple(req.version):
                if not release_is_eligible(base_pkg, target_version):
                    print(
                        f"Skipping {base_pkg} {target_version}: "
                        f"release is less than {MIN_RELEASE_AGE_DAYS} days old or unavailable"
                    )
                    updated_lines.append(line)
                    continue
                new_line = rebuild_line(req, target_version)
                if new_line != line:
                    updated_lines.append(new_line)
                    file_changed = True
                    changes.append(
                        f"{path}: {req.package} {req.operator}{req.version} -> {req.operator}{target_version} (published PHACC release)"
                    )
                else:
                    updated_lines.append(line)
            else:
                updated_lines.append(line)
            continue

        if base_pkg in PYTEST_HA_DEPENDENT_PACKAGES and base_pkg in pytest_ha_reqs:
            target_version = pytest_ha_reqs[base_pkg]
            target_source = "published PHACC release"

            if base_pkg == "homeassistant" and is_homeassistant_beta(target_version):
                stable_homeassistant = fetch_latest_version(base_pkg)
                if stable_homeassistant:
                    target_version = stable_homeassistant
                    target_source = "latest stable version from PyPI (PHACC target is beta)"
                else:
                    updated_lines.append(line)
                    changes.append(
                        f"{path}: {req.package} {req.operator}{req.version} -> {req.operator}{target_version} (SKIPPED - beta version)"
                    )
                    continue

            if target_version == req.version:
                updated_lines.append(line)
            elif numeric_tuple(target_version) >= numeric_tuple(req.version):
                if not release_is_eligible(base_pkg, target_version):
                    print(
                        f"Skipping {base_pkg} {target_version}: "
                        f"release is less than {MIN_RELEASE_AGE_DAYS} days old or unavailable"
                    )
                    updated_lines.append(line)
                    continue
                new_line = rebuild_line(req, target_version)
                if new_line != line:
                    updated_lines.append(new_line)
                    file_changed = True
                    changes.append(
                        f"{path}: {req.package} {req.operator}{req.version} -> {req.operator}{target_version} ({target_source})"
                    )
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


def update_readme(
    homeassistant_version: Optional[str], changes: List[str], python_version: str,
    tested_homeassistant_version: Optional[str] = None,
) -> None:
    """Update README with the documented Home Assistant compatibility version."""
    if not homeassistant_version or not README_PATH.exists():
        return

    text = README_PATH.read_text(encoding="utf-8")
    updated = False

    def _replace_version(match: re.Match[str]) -> str:
        return f"{match.group(1)}{homeassistant_version}{match.group(3)}"

    new_text, count = README_VERSION_PATTERN.subn(_replace_version, text, count=1)
    if count and new_text != text:
        text = new_text
        updated = True

    new_text, count = README_PYTHON_PATTERN.subn(
        lambda match: f"{match.group(1)}{python_version}{match.group(3)}", text, count=1
    )
    if count and new_text != text:
        text = new_text
        updated = True

    # Only a successful compatibility run may advance the documented test result.
    if tested_homeassistant_version:
        compat_match = README_COMPAT_PATTERN.search(text)
        if not compat_match or numeric_tuple(tested_homeassistant_version) >= numeric_tuple(compat_match.group(2)):
            compat_line = f"Zuletzt erfolgreich getestet mit Home Assistant {tested_homeassistant_version}."
            if compat_match:
                new_text = README_COMPAT_PATTERN.sub(lambda _: compat_line, text, count=1)
            else:
                new_text = text
                updates_heading = "## Updates\n\n"
                if updates_heading in text:
                    new_text = text.replace(updates_heading, f"{updates_heading}{compat_line}\n\n", 1)
            if new_text != text:
                text = new_text
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


def main(tested_homeassistant_version: Optional[str] = None) -> int:
    changes: List[str] = []
    if tested_homeassistant_version and not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", tested_homeassistant_version):
        raise SystemExit("The tested Home Assistant version must be a stable X.Y.Z release.")

    print('Selecting an age-eligible pytest-homeassistant-custom-component release...')
    pytest_ha_version = fetch_pytest_ha_version()
    if not pytest_ha_version:
        raise SystemExit("No age-eligible PHACC release available; files were not changed.")
    pytest_ha_reqs = fetch_pytest_ha_requirements(pytest_ha_version)
    if "homeassistant" not in pytest_ha_reqs:
        raise SystemExit("Selected PHACC release has no Home Assistant requirement; files were not changed.")
    print(f"Loaded {len(pytest_ha_reqs)} requirements from PHACC {pytest_ha_version}")

    target_ha = pytest_ha_reqs["homeassistant"]
    if is_homeassistant_beta(target_ha):
        target_ha = fetch_latest_version("homeassistant")
        if not target_ha:
            raise SystemExit("No age-eligible stable Home Assistant release available; files were not changed.")
        pytest_ha_reqs["homeassistant"] = target_ha

    # Validate metadata for both the existing and candidate versions before any writes.
    # An existing newer requirement may be retained by process_requirements_file.
    ha_versions = {extract_homeassistant_version(path) for path in REQ_FILES}
    ha_versions.discard(None)
    ha_versions.add(target_ha)
    python_versions: Dict[str, str] = {}
    for version in sorted(ha_versions):
        python_requires = fetch_package_info("homeassistant", version).get("requires_python", "")
        python_match = re.fullmatch(r">=([0-9]+(?:\.[0-9]+)*)", python_requires)
        if not python_match:
            raise SystemExit(f"Unsupported Home Assistant Python requirement: {python_requires}")
        python_versions[version] = python_match.group(1)

    for path in REQ_FILES:
        process_requirements_file(path, changes, pytest_ha_reqs, pytest_ha_version)
    process_manifest(MANIFEST_PATH, changes)

    ha_version = extract_homeassistant_version('requirements_test.txt')
    if ha_version is None:
        ha_version = extract_homeassistant_version('requirements.txt')
    if ha_version:
        update_readme(ha_version, changes, python_versions[ha_version], tested_homeassistant_version)

    if changes:
        print("Dependency updates applied:")
        for c in changes:
            print(f"- {c}")
        return 0
    else:
        print("No dependency updates available (patch/minor).")
        return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Update dependency requirements and README versions.")
    parser.add_argument(
        "--tested-homeassistant-version",
        help="Home Assistant version confirmed by a successful compatibility run.",
    )
    args = parser.parse_args()
    raise SystemExit(main(args.tested_homeassistant_version))
