import importlib.util
import contextlib
import io
import json
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

    def test_unversioned_action_keeps_package_advisories_and_unknown_applicability(self):
        finding={'ghsa_id':'GHSA-synthetic','cve_id':'CVE-2099-1234','severity':'high',
                 'summary':'synthetic','type':'reviewed','html_url':'https://example.invalid/advisory',
                 'vulnerabilities':[]}
        calls=[]
        def api(path):
            calls.append(path)
            if '/dependabot/alerts?' in path or '/tags?' in path:return []
            if path.startswith('advisories?'):return [finding]
            raise AssertionError(path)
        with tempfile.TemporaryDirectory() as tmp:
            output=io.StringIO()
            with patch.dict(os.environ,{'GITHUB_REPOSITORY':'example/project','GITHUB_SHA':'a'*40,
                    'GITHUB_OUTPUT':str(Path(tmp)/'output'),'GITHUB_STEP_SUMMARY':str(Path(tmp)/'summary')}), \
                    patch.object(m,'api',side_effect=api), \
                    patch.object(m,'action_references',return_value=[('upstream/validation','main')]), \
                    patch.object(m.Path,'is_file',return_value=False), \
                    patch.object(m.urllib.request,'urlopen',return_value=io.BytesIO(b'{"vulnerabilities":[{"cveID":"CVE-2099-1234"}]}')), \
                    contextlib.redirect_stdout(output):
                m.main()
                previous=output.getvalue()
                with patch.object(m,'affected',side_effect=RuntimeError('permission denied')):
                    with self.assertRaisesRegex(RuntimeError,'permission denied'):
                        m.main()
                self.assertEqual(output.getvalue(),previous)
            report=json.loads(output.getvalue().split('DEPENDENCY_REPORT ',1)[1])
            item=report['unmapped_actions'][0]
            self.assertEqual(item['applicability'],'unknown')
            self.assertEqual(item['advisory_scope'],'package')
            self.assertEqual(item['findings'][0]['id'],'GHSA-synthetic')
            self.assertEqual(report['actions'],[])
            self.assertEqual(len(report['known_exploited']),1)
            queries=[p for p in calls if p.startswith('advisories?')]
            self.assertEqual(len(queries),2)
            self.assertTrue(all('affects=upstream%2Fvalidation&' in p and '%40main' not in p for p in queries))


if __name__=='__main__':unittest.main()
