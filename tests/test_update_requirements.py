from datetime import datetime, timezone
import io
import json
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys
from urllib.error import URLError

import pytest


SCRIPT_PATH = Path(__file__).parents[1] / ".github" / "scripts" / "update_requirements.py"
SPEC = spec_from_file_location("update_requirements", SCRIPT_PATH)
assert SPEC and SPEC.loader
UPDATE_REQUIREMENTS = module_from_spec(SPEC)
sys.modules[SPEC.name] = UPDATE_REQUIREMENTS
SPEC.loader.exec_module(UPDATE_REQUIREMENTS)


def release_file(upload_time: str, *, yanked: bool = False) -> dict:
    return {"upload_time_iso_8601": upload_time, "yanked": yanked}


def test_eligible_stable_versions_excludes_fresh_and_yanked_releases() -> None:
    releases = {
        "1.2.0": [release_file("2026-08-20T12:00:00Z")],
        "1.2.1": [release_file("2026-08-21T12:00:01Z")],
        "1.2.2": [release_file("2026-08-19T12:00:00Z", yanked=True)],
        "1.3.0rc1": [release_file("2026-08-01T12:00:00Z")],
    }

    eligible = UPDATE_REQUIREMENTS.eligible_stable_versions(
        releases,
        now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
    )

    assert eligible == ["1.2.0"]


def test_eligible_stable_versions_requires_all_files_to_reach_minimum_age() -> None:
    releases = {
        "2.0.0": [
            release_file("2026-08-20T11:59:00Z"),
            release_file("2026-08-21T12:01:00Z"),
        ]
    }

    eligible = UPDATE_REQUIREMENTS.eligible_stable_versions(
        releases,
        now=datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc),
    )

    assert eligible == []


def test_update_uses_eligible_test_stack_when_upstream_is_fresh(monkeypatch, tmp_path):
    package = "pytest-homeassistant-custom-component"
    old = [release_file("2000-01-01T00:00:00Z")]
    fresh = [release_file("2999-01-01T00:00:00Z")]
    responses = {
        "https://raw.githubusercontent.com/MatthewFlamm/pytest-homeassistant-custom-component/master/version": "0.13.374",
        "https://raw.githubusercontent.com/MatthewFlamm/pytest-homeassistant-custom-component/master/requirements_test.txt": "homeassistant==2026.10.3\n",
        f"https://pypi.org/pypi/{package}/json": {
            "releases": {"0.13.373": old, "0.13.374": fresh},
        },
        f"https://pypi.org/pypi/{package}/0.13.373/json": {
            "info": {"requires_dist": ["homeassistant==2026.10.2"]},
        },
        "https://pypi.org/pypi/homeassistant/json": {
            "releases": {"2026.10.2": old, "2026.10.3": fresh},
        },
        "https://pypi.org/pypi/homeassistant/2026.10.2/json": {
            "info": {"requires_python": ">=3.14.2"},
        },
        "https://pypi.org/pypi/homeassistant/2026.9.3/json": {
            "info": {"requires_python": ">=3.13.2"},
        },
    }

    def urlopen(url, *, timeout):
        value = responses[url]
        return io.BytesIO((value if isinstance(value, str) else json.dumps(value)).encode())

    monkeypatch.setattr(UPDATE_REQUIREMENTS.urllib.request, "urlopen", urlopen)
    monkeypatch.chdir(tmp_path)
    requirements = tmp_path / "requirements_test.txt"
    requirements.write_text(
        f"homeassistant >= 2026.9.3\n{package} >= 0.13.356\n",
        encoding="utf-8",
    )
    readme = tmp_path / "README.md"
    readme.write_text(
        "- Python 3.13.2 oder neuer\n- Home Assistant 2026.9.3 oder neuer\n\n"
        "## Updates\n\nZuletzt erfolgreich getestet mit Home Assistant 2026.9.3.\n",
        encoding="utf-8",
    )

    assert UPDATE_REQUIREMENTS.main("2026.10.3") == 0
    assert requirements.read_text() == (
        f"homeassistant >= 2026.10.2\n{package} >= 0.13.373\n"
    )
    assert "Python 3.14.2 oder neuer" in readme.read_text()
    assert "Home Assistant 2026.10.2 oder neuer" in readme.read_text()
    assert "Zuletzt erfolgreich getestet mit Home Assistant 2026.10.3." in readme.read_text()
    before = (requirements.read_bytes(), readme.read_bytes())
    assert UPDATE_REQUIREMENTS.main("2026.10.3") == 0
    assert before == (requirements.read_bytes(), readme.read_bytes())


@pytest.mark.parametrize("version", [None, "0.13.373"])
def test_missing_test_stack_metadata_stops_before_editing(monkeypatch, tmp_path, version):
    monkeypatch.chdir(tmp_path)
    requirements = tmp_path / "requirements_test.txt"
    original = "homeassistant >= 2026.9.3\n"
    requirements.write_text(original, encoding="utf-8")
    monkeypatch.setattr(UPDATE_REQUIREMENTS, "fetch_pytest_ha_version", lambda: version)
    monkeypatch.setattr(UPDATE_REQUIREMENTS, "fetch_pytest_ha_requirements", lambda _: {})

    message = "No age-eligible PHACC release" if version is None else "no Home Assistant requirement"
    with pytest.raises(SystemExit, match=message):
        UPDATE_REQUIREMENTS.main()

    assert requirements.read_text() == original


@pytest.mark.parametrize("tested_version", [None, "2026.10.1"])
def test_dependency_update_preserves_newer_successful_test_result(monkeypatch, tmp_path, tested_version):
    monkeypatch.chdir(tmp_path)
    readme = tmp_path / "README.md"
    readme.write_text(
        "- Python 3.13.2 oder neuer\n- Home Assistant 2026.9.3 oder neuer\n\n"
        "## Updates\n\nZuletzt erfolgreich getestet mit Home Assistant 2026.10.3.\n",
        encoding="utf-8",
    )

    if tested_version is None:
        UPDATE_REQUIREMENTS.update_readme("2026.10.2", [], "3.14.2")
    else:
        UPDATE_REQUIREMENTS.update_readme("2026.10.2", [], "3.14.2", tested_version)

    assert "Home Assistant 2026.10.2 oder neuer" in readme.read_text()
    assert "Zuletzt erfolgreich getestet mit Home Assistant 2026.10.3." in readme.read_text()


@pytest.mark.parametrize("metadata", [{}, {"requires_python": ">=3.14.2,<3.15"}, None])
def test_invalid_python_metadata_stops_before_editing(monkeypatch, tmp_path, metadata):
    monkeypatch.chdir(tmp_path)
    requirements = tmp_path / "requirements_test.txt"
    original = "homeassistant >= 2026.9.3\n"
    requirements.write_text(original, encoding="utf-8")
    monkeypatch.setattr(UPDATE_REQUIREMENTS, "fetch_pytest_ha_version", lambda: "0.13.373")
    monkeypatch.setattr(
        UPDATE_REQUIREMENTS, "fetch_pytest_ha_requirements",
        lambda _: {"homeassistant": "2026.10.2"},
    )

    def package_info(package, version):
        if metadata is None:
            raise URLError("metadata unavailable")
        return metadata

    monkeypatch.setattr(UPDATE_REQUIREMENTS, "fetch_package_info", package_info)
    if metadata is None:
        with pytest.raises(URLError, match="metadata unavailable"):
            UPDATE_REQUIREMENTS.main()
    else:
        with pytest.raises(SystemExit, match="Unsupported Home Assistant Python requirement"):
            UPDATE_REQUIREMENTS.main()

    assert requirements.read_text() == original
