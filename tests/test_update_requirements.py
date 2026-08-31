from datetime import datetime, timezone
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


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
