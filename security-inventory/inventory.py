#!/usr/bin/env python3
"""Öffentliche Sicherheitshinweise zu Projektabhängigkeiten zusammenfassen."""
from functools import lru_cache
import json
import os
from pathlib import Path
import re
import subprocess
import urllib.parse
import urllib.request


def api(path):
    result = subprocess.run(['gh', 'api', '--paginate', '--slurp', path],
                            capture_output=True, text=True, check=True, timeout=120)
    pages = json.loads(result.stdout)
    if not isinstance(pages, list) or any(not isinstance(page, list) for page in pages):
        raise ValueError('Unvollständige GitHub-Liste')
    return [entry for page in pages for entry in page]


@lru_cache(maxsize=None)
def action_versions(repository, reference):
    if re.fullmatch(r'v?\d+\.\d+\.\d+', reference):
        return [reference.removeprefix('v')]
    tags = api(f'repos/{repository}/tags?per_page=100')
    if re.fullmatch('[a-f0-9]{40}', reference):
        commits = {reference}
    else:
        commits = {tag['commit']['sha'] for tag in tags if tag['name'] == reference}
    return sorted({tag['name'].removeprefix('v') for tag in tags
                   if tag['commit']['sha'] in commits and re.fullmatch(r'v?\d+\.\d+\.\d+', tag['name'])})


def affected(ecosystem, packages):
    findings = {}
    for kind in ('reviewed', 'malware'):
        query = urllib.parse.urlencode({'ecosystem': ecosystem, 'affects': ','.join(packages),
                                        'type': kind, 'is_withdrawn': 'false', 'per_page': 100})
        for finding in api('advisories?' + query):
            findings[finding['ghsa_id']] = finding.get('cve_id')
    return findings


def action_references(directory):
    references = set()
    for path in directory.glob('*.y*ml'):
        for repository, reference in re.findall(
                r"(?m)^\s*(?:-\s*)?uses:\s*['\"]?([\w.-]+/[\w.-]+)(?:/[\w./-]+)?@([^\s#'\"]+)", path.read_text()):
            if not reference.startswith('${'):
                references.add((repository, reference))
    return sorted(references)


def main():
    # Öffentliche Läufe liefern nur eine Zusammenfassung aus öffentlichen Katalogen.
    owner = os.environ['GITHUB_REPOSITORY'].split('/')[0].lower()
    version_findings = {}
    unmapped_actions = 0
    package_findings = {}
    for action, reference in action_references(Path('.github/workflows')):
        # Organization-owned components are reviewed with their own repositories.
        if action.split('/')[0].lower() == owner:
            continue
        versions = action_versions(action, reference)
        if not versions:
            unmapped_actions += 1
            package_findings.update(affected('actions', [action]))
            continue
        version_findings.update(affected('actions', [action + '@' + version for version in versions]))
    version_file = Path('swagger-ui.version')
    if version_file.is_file():
        version = version_file.read_text().strip().removeprefix('v')
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('Ungültige vendorte Swagger-UI-Version')
        version_findings.update(affected('npm', ['swagger-ui@' + version, 'swagger-ui-dist@' + version]))
    request = urllib.request.Request('https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json',
                                     headers={'User-Agent': 'github-dependency-inventory'})
    with urllib.request.urlopen(request, timeout=30) as response:
        kev = json.load(response)
    if not isinstance(kev.get('vulnerabilities'), list) or not kev['vulnerabilities']:
        raise ValueError('CISA-Katalog fehlt')
    matched_cves = set(version_findings.values())
    known_exploited = {entry['cveID'] for entry in kev['vulnerabilities'] if entry['cveID'] in matched_cves}
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
        stream.write(
            '### Öffentliche Sicherheitskataloge\n\n'
            f'- Öffentliche Sicherheitshinweise zu geprüften Versionen ({len(version_findings)})\n'
            f'- Zugehörige CVE im CISA-Katalog ({len(known_exploited)})\n'
            f'- Action-Referenzen ohne eindeutige Versionszuordnung ({unmapped_actions})\n'
            f'- Öffentliche Pakethinweise mit ungeklärter Anwendbarkeit ({len(package_findings)})\n'
        )


if __name__ == '__main__':
    main()
