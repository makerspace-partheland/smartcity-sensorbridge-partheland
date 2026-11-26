#!/usr/bin/env python3
"""Native GitHub-Meldungen zusammenstellen; keine Installation oder Sicherheitsausnahme."""
from datetime import datetime, timezone
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
            findings[finding['ghsa_id']] = {'id': finding['ghsa_id'], 'cve': finding.get('cve_id'),
              'severity': finding['severity'], 'summary': finding['summary'], 'type': finding['type'],
              'url': finding['html_url'], 'vulnerabilities': finding['vulnerabilities']}
    return list(findings.values())


def action_references(directory):
    references = set()
    for path in directory.glob('*.y*ml'):
        for repository, reference in re.findall(
                r"(?m)^\s*(?:-\s*)?uses:\s*['\"]?([\w.-]+/[\w.-]+)(?:/[\w./-]+)?@([^\s#'\"]+)", path.read_text()):
            if not reference.startswith('${'):
                references.add((repository, reference))
    return sorted(references)


def main():
    repository = os.environ['GITHUB_REPOSITORY']
    report = {'schema': 1, 'repository': repository, 'source_sha': os.environ['GITHUB_SHA'],
              'checked_at': datetime.now(timezone.utc).isoformat(), 'dependabot': [],
              'actions': [], 'unmapped_actions': [], 'vendored': []}
    for alert in api(f'repos/{repository}/dependabot/alerts?state=open&per_page=100'):
        report['dependabot'].append({'number': alert['number'], 'package': alert['dependency']['package'],
          'manifest': alert['dependency']['manifest_path'], 'id': alert['security_advisory']['ghsa_id'],
          'cve': alert['security_advisory'].get('cve_id'), 'severity': alert['security_advisory']['severity'],
          'fixed': alert['security_vulnerability'].get('first_patched_version'), 'url': alert['html_url']})
    owner = repository.split('/')[0].lower()
    for action, reference in action_references(Path('.github/workflows')):
        # Organization-owned components are reviewed with their own repositories.
        if action.split('/')[0].lower() == owner:
            continue
        versions = action_versions(action, reference)
        if not versions:
            report['unmapped_actions'].append({'repository': action, 'reference': reference,
                'advisory_scope': 'package', 'applicability': 'unknown',
                'findings': affected('actions', [action])})
            continue
        report['actions'].append({'repository': action, 'reference': reference, 'versions': versions,
                                  'findings': affected('actions', [action + '@' + version for version in versions])})
    version_file = Path('swagger-ui.version')
    if version_file.is_file():
        version = version_file.read_text().strip().removeprefix('v')
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('Ungültige vendorte Swagger-UI-Version')
        report['vendored'].append({'package': 'swagger-ui', 'version': version,
                                  'findings': affected('npm', ['swagger-ui@' + version, 'swagger-ui-dist@' + version])})
    request = urllib.request.Request('https://www.cisa.gov/sites/default/files/feeds/known_exploited_vulnerabilities.json',
                                     headers={'User-Agent': 'github-dependency-inventory'})
    with urllib.request.urlopen(request, timeout=30) as response:
        kev = json.load(response)
    if not isinstance(kev.get('vulnerabilities'), list) or not kev['vulnerabilities']:
        raise ValueError('CISA-Katalog fehlt')
    identifiers = set(re.findall(r'CVE-\d{4}-\d+', json.dumps(report)))
    report['known_exploited'] = [v for v in kev['vulnerabilities'] if v['cveID'] in identifiers]
    print('DEPENDENCY_REPORT ' + json.dumps(report, sort_keys=True))
    with open(os.environ['GITHUB_OUTPUT'], 'a') as stream:
        stream.write('report=' + json.dumps(report, separators=(',', ':')) + '\n')
    with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as stream:
        stream.write('Aktuelle Dependabot-, Action- und gegebenenfalls Swagger-Meldungen wurden erfasst. '
                     'Ein erfolgreicher Abruf bedeutet nicht, dass offene Befunde behoben sind.\n')


if __name__ == '__main__':
    main()
