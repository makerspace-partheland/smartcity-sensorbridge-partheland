"""Prüft Repository-Alerts und öffentliche Hinweise zu verwendeten Actions."""

import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API = "https://api.github.com"
KEV = "https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json"
REPO = "makerspace-partheland/smartcity-sensorbridge-partheland"
ACTION = re.compile(r"^\s*-?\s*uses:\s*['\"]?([\w.-]+/[\w.-]+)(?:/[\w./-]+)?@([\w.-]+)", re.M)
VERSION = re.compile(r"^v?(\d+\.\d+\.\d+)$")


def get(url, github=True):
    headers = {"User-Agent": "sensorbridge-security-check", "Accept": "application/vnd.github+json"}
    request = Request(url, headers=headers)
    if github:
        if not url.startswith(API + "/"):
            raise ValueError("invalid API origin")
        request.add_unredirected_header("Authorization", "Bearer " + os.environ["GH_TOKEN"])
        request.add_header("X-GitHub-Api-Version", "2022-11-28")
    with urlopen(request, timeout=30) as response:
        return json.load(response), response.headers.get("Link", "")


def pages(url):
    while url:
        data, links = get(url)
        if not isinstance(data, list):
            raise ValueError("invalid response")
        yield from data
        next_link = re.search(r'<([^>]+)>;\s*rel="next"', links)
        url = next_link.group(1) if next_link else None
        if url and not url.startswith(API + "/"):
            raise ValueError("invalid pagination")


def check_private_alerts():
    """Meldungen nur im Speicher prüfen; Details bleiben in GitHub geschützt."""
    for alert in pages(f"{API}/repos/{REPO}/dependabot/alerts?state=open&per_page=100"):
        dependency = alert.get("dependency") or {}
        advisory = alert.get("security_advisory") or {}
        vulnerability = alert.get("security_vulnerability") or {}
        package = dependency.get("package") or vulnerability.get("package") or {}
        patched = vulnerability.get("first_patched_version")
        fix = patched.get("identifier") if isinstance(patched, dict) else patched
        severities = (vulnerability["severity"], advisory["severity"])
        if (not alert.get("url", "").startswith(f"{API}/repos/{REPO}/dependabot/alerts/")
                or alert.get("state") != "open"
                or any(value not in {"unknown", "low", "medium", "high", "critical"} for value in severities)
                or not isinstance(package.get("name"), str) or not package["name"].strip()
                or not isinstance(package.get("ecosystem"), str) or not package["ecosystem"].strip()
                or (patched is not None and
                    (not isinstance(patched, dict) or not isinstance(fix, str) or not fix.strip()))):
            raise ValueError("invalid alert response")


def action_versions():
    refs = set()
    for path in Path(".github/workflows").glob("*.yml"):
        refs.update(ACTION.findall(path.read_text(encoding="utf-8")))
    for path in Path(".github/workflows").glob("*.yaml"):
        refs.update(ACTION.findall(path.read_text(encoding="utf-8")))
    for repo, ref in sorted(refs):
        if ref == "main":
            yield repo, ref, None
            continue
        if VERSION.fullmatch(ref):
            yield repo, ref, VERSION.fullmatch(ref).group(1)
            continue
        # Bewegliche Tags und SHA-Pins nur bei eindeutig passendem Release-Tag zuordnen.
        commit, _ = get(f"{API}/repos/{repo}/commits/{ref}")
        sha = commit["sha"]
        versions = {match.group(1) for tag in pages(f"{API}/repos/{repo}/tags?per_page=100")
                    if (match := VERSION.fullmatch(tag.get("name", "")))
                    and tag.get("commit", {}).get("sha") == sha}
        yield repo, ref, next(iter(versions)) if len(versions) == 1 else None


def public_advisories():
    kev, _ = get(KEV, github=False)
    entries = kev.get("vulnerabilities")
    if not isinstance(entries, list) or not entries:
        raise ValueError("invalid catalog")
    exploited = set()
    for entry in entries:
        cve = entry.get("cveID")
        if not isinstance(cve, str) or not re.fullmatch(r"CVE-\d{4}-\d{4,}", cve):
            raise ValueError("invalid catalog entry")
        exploited.add(cve)
    found = {}
    unresolved = {}
    for repo, ref, version in action_versions():
        for kind in ("reviewed", "malware"):
            query = urlencode({"ecosystem": "actions", "type": kind,
                               "affects": f"{repo}@{version}" if version else repo,
                               "per_page": 100, "is_withdrawn": "false"})
            for advisory in pages(f"{API}/advisories?{query}"):
                identifier = advisory.get("ghsa_id", "")
                if not re.fullmatch(r"GHSA-[a-z0-9]{4}-[a-z0-9]{4}-[a-z0-9]{4}", identifier):
                    raise ValueError("invalid advisory")
                severity = advisory.get("severity")
                if severity not in {"unknown", "low", "medium", "high", "critical"}:
                    raise ValueError("invalid advisory severity")
                if version:
                    found[identifier] = (severity, advisory.get("cve_id") in exploited)
                else:
                    unresolved.setdefault(repo, set()).add(identifier)
        if not version:
            unresolved.setdefault(repo, set())
    counts = {severity: 0 for severity in ("critical", "high", "medium", "low", "unknown")}
    for severity, _ in found.values():
        counts[severity] += 1
    print("Öffentliche Hinweise zu eindeutig zugeordneten Versionen:", json.dumps(counts))
    print("Davon im CISA-Katalog:", sum(kev for _, kev in found.values()))
    for repo, entries in sorted(unresolved.items()):
        print(f"{repo}: {len(entries)} Hinweise mit ungeklärter Anwendbarkeit")


def main():
    try:
        check_private_alerts()
    except Exception:
        print("Dependabot-Daten konnten technisch nicht abgerufen werden.", file=sys.stderr)
        return 1
    try:
        public_advisories()
    except Exception:
        print("Öffentliche Hinweise konnten technisch nicht geprüft werden.", file=sys.stderr)
        return 1
    print("Die technische Prüfung wurde abgeschlossen.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
