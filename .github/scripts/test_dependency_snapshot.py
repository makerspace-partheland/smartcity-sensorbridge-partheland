import io
import json
import os
import textwrap
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
from dependency_snapshot import installed_packages


def report(packages):
    return {"version": "1", "installed": [
        {"metadata": {"name": name, "version": version}} for name, version in packages
    ]}


class DependencySnapshotTests(unittest.TestCase):
    def test_exact_installed_versions_include_unrequested_transitive_packages(self):
        value = report([("Parent_Package", "2.0"), ("child.package", "1.4+local")])
        value["installed"][1]["requested"] = False
        value["installed"][0]["direct_url"] = {"url": "https://secret.invalid/private"}
        value["installed"][0]["metadata_location"] = "/private/build/path"
        value["installed"][0]["metadata"]["description"] = "private metadata"
        self.assertEqual(
            json.loads(installed_packages(value)),
            [["child-package", "1.4+local"], ["parent-package", "2.0"]],
        )

    def test_five_hundred_packages_fit_the_bounded_output(self):
        packages = [(f"package-{n}", "2026.11.1") for n in range(500)]
        self.assertEqual(len(json.loads(installed_packages(report(packages)))), 500)

    def test_unknown_format_and_empty_inventory_fail(self):
        with self.assertRaisesRegex(ValueError, "Format"):
            installed_packages({"version": "2", "installed": []})
        with self.assertRaisesRegex(ValueError, "Paketliste"):
            installed_packages(report([]))

    def test_names_versions_and_duplicate_normalized_names_are_rejected(self):
        for packages, message in [
            ([("bad\nname", "1")], "Paketname"),
            ([("package", "1\noutput=value")], "Paketversion"),
            ([("Some_Package", "1"), ("some-package", "2")], "mehrfach"),
        ]:
            with self.subTest(packages=packages):
                with self.assertRaisesRegex(ValueError, message):
                    installed_packages(report(packages))

    def test_oversized_output_fails_instead_of_truncating_inventory(self):
        packages = [(f"package-{n}", "1" * 128) for n in range(500)]
        with self.assertRaisesRegex(ValueError, "Joboutput"):
            installed_packages(report(packages))


class SubmissionBoundaryTests(unittest.TestCase):
    def setUp(self):
        workflow = Path(__file__).parents[1] / "workflows/submit-test-dependencies.yml"
        source = workflow.read_text().split("          python3 - <<'PY'\n", 1)[1]
        self.source = textwrap.dedent(source.rsplit("          PY", 1)[0])
        self.environment = {
            "PACKAGES": '[["parent-package","2.0"],["child-package","1.4+local"]]',
            "TEST_SCOPE": "ha",
            "GITHUB_REPOSITORY": "makerspace-partheland/smartcity-sensorbridge-partheland",
            "GITHUB_SHA": "a" * 40,
            "GITHUB_RUN_ID": "123",
            "GITHUB_RUN_ATTEMPT": "1",
            "GH_TOKEN": "synthetic-test-token",
        }

    @staticmethod
    def response(value, status=200):
        response = io.BytesIO(json.dumps(value).encode())
        response.status = status
        return response

    def test_native_snapshot_contains_only_exact_development_packages(self):
        responses = [self.response({"sha": "a" * 40}), self.response({}, 201)]
        with patch.dict(os.environ, self.environment, clear=True):
            with patch("urllib.request.urlopen", side_effect=responses) as request:
                exec(compile(self.source, "submission-workflow", "exec"), {})
        self.assertEqual(request.call_count, 2)
        sent = request.call_args_list[1].args[0]
        self.assertEqual(sent.method, "POST")
        self.assertTrue(sent.full_url.endswith("/dependency-graph/snapshots"))
        snapshot = json.loads(sent.data)
        self.assertEqual(snapshot["job"]["correlator"], "sensorbridge-tests-ha")
        self.assertEqual(snapshot["sha"], "a" * 40)
        self.assertEqual(snapshot["ref"], "refs/heads/main")
        resolved = snapshot["manifests"]["sensorbridge-tests-ha"]["resolved"]
        self.assertEqual(set(resolved), {
            "pkg:pypi/parent-package@2.0", "pkg:pypi/child-package@1.4%2Blocal"
        })
        self.assertTrue(all(item["scope"] == "development" for item in resolved.values()))
        self.assertTrue(all(set(item) == {"package_url", "scope"} for item in resolved.values()))

    def test_invalid_output_is_rejected_before_any_network_access(self):
        for values in [
            {"PACKAGES": "[]"},
            {"PACKAGES": '[["bad/name","1"]]'},
            {"PACKAGES": '[["package","1\\noutput=value"]]'},
            {"PACKAGES": '[["package","1"],["package","2"]]'},
            {"PACKAGES": " " * (48 * 1024 + 1)},
            {"TEST_SCOPE": "production"},
        ]:
            with self.subTest(values=values):
                with patch.dict(os.environ, {**self.environment, **values}, clear=True):
                    with patch("urllib.request.urlopen") as request:
                        with self.assertRaises(ValueError):
                            exec(compile(self.source, "submission-workflow", "exec"), {})
                        request.assert_not_called()

    def test_superseded_main_commit_does_not_submit_a_snapshot(self):
        with patch.dict(os.environ, self.environment, clear=True):
            with patch("urllib.request.urlopen", return_value=self.response({"sha": "b" * 40})) as request:
                exec(compile(self.source, "submission-workflow", "exec"), {})
        self.assertEqual(request.call_count, 1)


class WorkflowPermissionBoundaryTests(unittest.TestCase):
    def test_reusable_ha_test_remains_read_only_for_its_weekly_caller(self):
        workflows = Path(__file__).parents[1] / "workflows"
        ha = (workflows / "post-merge-ha-test.yml").read_text()
        weekly = (workflows / "update-dependencies.yml").read_text()
        self.assertIn("permissions:\n  contents: read", ha)
        self.assertNotIn("contents: write", ha)
        self.assertNotIn("submit-test-dependencies.yml", ha)
        self.assertIn("value: ${{ jobs.ha-compatibility-test.outputs.packages }}", ha)
        compatibility = weekly.split("  compatibility:\n", 1)[1].split("\n  dependency-graph:", 1)[0]
        self.assertNotIn("contents: write", compatibility)
        self.assertNotIn("secrets:", compatibility)
        metadata = weekly.split("  dependency-graph:\n", 1)[1].split("\n  update:", 1)[0]
        self.assertIn("needs: compatibility", metadata)
        self.assertIn("needs.compatibility.outputs.packages != ''", metadata)
        self.assertIn("uses: ./.github/workflows/submit-test-dependencies.yml", metadata)
        self.assertIn("test-scope: ha", metadata)

    def test_submission_guard_accepts_only_trusted_protected_main_events(self):
        workflow = Path(__file__).parents[1] / "workflows/submit-test-dependencies.yml"
        source = workflow.read_text()
        guard = source.split("    if: >-\n", 1)[1].split("    runs-on:", 1)[0]
        for event in ("push", "schedule", "workflow_dispatch", "pull_request", "pull_request_target"):
            for protected in (False, True):
                for ref in ("refs/heads/main", "refs/heads/other"):
                    for own_repository in (False, True):
                        expression = guard.replace(
                            "github.repository", repr("makerspace-partheland/smartcity-sensorbridge-partheland"
                                                      if own_repository else "example/fork")
                        ).replace("github.event_name", repr(event)).replace(
                            "github.ref_protected", repr(protected)
                        ).replace("github.ref", repr(ref))
                        expression = " ".join(expression.split()).replace("&&", "and").replace("||", "or")
                        expected = (event in ("push", "schedule", "workflow_dispatch")
                                    and protected and ref == "refs/heads/main" and own_repository)
                        with self.subTest(event=event, protected=protected, ref=ref, own_repository=own_repository):
                            self.assertEqual(eval(expression, {"__builtins__": {}}), expected)


if __name__ == "__main__":
    unittest.main()
