"""Release selection stays safe when the public release history is reset."""

import importlib.util
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "packaging" / "select-update-baseline.py"
WORKFLOW = (ROOT / ".github" / "workflows" / "build.yml").read_text()

SPEC = importlib.util.spec_from_file_location("select_update_baseline", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def release(tag, *, prerelease=False, draft=False):
    return {"tag_name": tag, "prerelease": prerelease, "draft": draft}


def test_newest_lower_stable_release_is_preferred():
    releases = [
        release("v0.8.0", prerelease=True),
        release("v0.7.0"),
        release("v0.6.0"),
    ]
    assert MODULE.select_update_baseline(releases, "0.9.0") == "v0.7.0"


def test_prerelease_is_used_after_a_release_history_reset():
    releases = [release("v0.9.0", prerelease=True)]
    assert MODULE.select_update_baseline(releases, "0.10.0") == "v0.9.0"


def test_same_version_is_not_an_update_baseline():
    releases = [release("v0.9.0", prerelease=True)]
    assert MODULE.select_update_baseline(releases, "0.9.0") is None


def test_drafts_invalid_tags_and_newer_versions_are_ignored():
    releases = [
        release("v0.8.0", draft=True),
        release("not-a-version"),
        release("v1.0.0"),
    ]
    assert MODULE.select_update_baseline(releases, "0.9.0") is None


def test_paginated_slurp_output_is_supported():
    releases = [[release("v0.7.0")], [release("v0.8.0")]]
    assert MODULE.select_update_baseline(releases, "0.9.0") == "v0.8.0"


def test_no_baseline_has_a_distinct_command_exit_code(tmp_path):
    response = tmp_path / "releases.json"
    response.write_text(json.dumps([release("v0.9.0", prerelease=True)]))
    result = subprocess.run(
        [sys.executable, str(SCRIPT), str(response), "0.9.0"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == MODULE.NO_BASELINE
    assert "no published release exists below 0.9.0" in result.stderr


def test_workflow_only_skips_the_missing_baseline_for_non_tag_builds():
    assert "packaging/select-update-baseline.py" in WORKFLOW
    assert 'if [[ "$GITHUB_REF" == refs/tags/v* ]]' in WORKFLOW
    assert "release-tag builds require a published lower-version updater baseline" in WORKFLOW
    assert WORKFLOW.count("env.HAS_UPDATE_BASELINE == 'true'") == 2


def test_a_release_that_cannot_update_itself_is_never_the_starting_point():
    """0.10.x before 0.10.5 cannot install any update (see self_update's
    relaunch check), so a smoke that started there would test only that bug.
    The newest release that can is used instead."""

    releases = [release("v0.10.4"), release("v0.9.1"), release("v0.9.0")]
    assert MODULE.select_update_baseline(releases, "0.10.5") == "v0.9.1"
    # Releases after the fix are ordinary baselines again.
    assert MODULE.select_update_baseline(
        releases + [release("v0.10.5")], "0.10.6") == "v0.10.5"
