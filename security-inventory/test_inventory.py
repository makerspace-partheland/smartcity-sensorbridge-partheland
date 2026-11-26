import importlib.util
import contextlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('inventory',Path(__file__).with_name('inventory.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class InventoryTests(unittest.TestCase):
    def setUp(self):
        m.action_versions.cache_clear()

    def test_pinned_commit_resolves_only_its_real_version_tags(self):
        tags=[{'name':'v7','commit':{'sha':'a'*40}}, {'name':'v7.0.1','commit':{'sha':'a'*40}},
              {'name':'v7.0.2','commit':{'sha':'b'*40}}]
        with patch.object(m,'api',return_value=tags):
            self.assertEqual(m.action_versions('actions/checkout','a'*40),['7.0.1'])
            self.assertEqual(m.action_versions('actions/checkout','v7'),['7.0.1'])
            self.assertEqual(m.action_versions('actions/checkout','c'*40),[])

    def test_workflow_data_does_not_become_a_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'example.yml').write_text('uses: actions/checkout@'+'a'*40+' # v7\n  - uses: "docker/login-action@v4.8.0"\n  uses: ./local\n  uses: ${{ matrix.action }}\n')
            self.assertEqual(m.action_references(p),[('actions/checkout','a'*40),('docker/login-action','v4.8.0')])

    def test_advisories_cover_reviewed_and_malware_without_duplicates(self):
        finding={'ghsa_id':'GHSA-test','cve_id':'CVE-2099-1234','severity':'high','summary':'synthetic',
                 'type':'reviewed','html_url':'https://github.com/advisories/GHSA-test','vulnerabilities':[]}
        with patch.object(m,'api',return_value=[finding]) as api:
            values=m.affected('npm',['swagger-ui@5.0.1'])
            self.assertEqual(len(values),1)
            self.assertIn('type=reviewed',api.call_args_list[0].args[0])
            self.assertIn('type=malware',api.call_args_list[1].args[0])
            self.assertIn('affects=swagger-ui%405.0.1',api.call_args_list[0].args[0])

    def test_api_failure_is_not_a_clean_empty_report(self):
        with patch.object(m,'api',side_effect=RuntimeError('permission denied')):
            with self.assertRaisesRegex(RuntimeError,'permission denied'):
                m.affected('actions',['actions/checkout@7.0.1'])

    def test_main_only_publishes_a_summary_of_public_sources(self):
        versioned_finding = {'ghsa_id': 'GHSA-versioned', 'cve_id': 'CVE-2099-1234'}
        package_finding = {'ghsa_id': 'GHSA-package', 'cve_id': 'CVE-2099-4567'}

        def public_api(path):
            if path == 'repos/upstream/validation/tags?per_page=100':
                return []
            if path.startswith('advisories?'):
                if 'affects=actions%2Fcheckout%407.0.1&' in path:
                    return [versioned_finding]
                if 'affects=upstream%2Fvalidation&' in path:
                    return [package_finding]
            raise AssertionError(path)

        with tempfile.TemporaryDirectory() as tmp:
            output_path = Path(tmp) / 'output'
            summary_path = Path(tmp) / 'summary'
            stdout = io.StringIO()
            environment = {'GITHUB_REPOSITORY': 'example/project', 'GITHUB_OUTPUT': str(output_path),
                           'GITHUB_STEP_SUMMARY': str(summary_path)}
            references = [('actions/checkout', 'v7.0.1'), ('upstream/validation', 'main')]
            kev = b'{"vulnerabilities":[{"cveID":"CVE-2099-1234"},{"cveID":"CVE-2099-4567"}]}'
            with patch.dict(os.environ, environment), \
                    patch.object(m, 'api', side_effect=public_api), \
                    patch.object(m, 'action_references', return_value=references), \
                    patch.object(m.Path, 'is_file', return_value=False), \
                    patch.object(m.urllib.request, 'urlopen', return_value=io.BytesIO(kev)), \
                    contextlib.redirect_stdout(stdout):
                m.main()

            self.assertEqual(stdout.getvalue(), '')
            self.assertFalse(output_path.exists())
            summary = summary_path.read_text()
            self.assertIn('Öffentliche Sicherheitshinweise zu geprüften Versionen (1)', summary)
            self.assertIn('Zugehörige CVE im CISA-Katalog (1)', summary)
            self.assertIn('Action-Referenzen ohne eindeutige Versionszuordnung (1)', summary)
            self.assertIn('Öffentliche Pakethinweise mit ungeklärter Anwendbarkeit (1)', summary)
            for detail in ('GHSA-', 'CVE-2099-', 'actions/checkout', 'upstream/validation'):
                self.assertNotIn(detail, summary)

            with patch.dict(os.environ, environment), \
                    patch.object(m, 'api', side_effect=RuntimeError('Abruf fehlgeschlagen')), \
                    patch.object(m, 'action_references', return_value=references):
                with self.assertRaisesRegex(RuntimeError, 'Abruf fehlgeschlagen'):
                    m.main()
            self.assertEqual(summary_path.read_text(), summary)


if __name__=='__main__':unittest.main()
