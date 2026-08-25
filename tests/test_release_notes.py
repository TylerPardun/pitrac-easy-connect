"""Release notes must describe the release they are attached to.

The workflow pointed body_path at a file named for v0.4.6, so every release
after it carried v0.4.6's notes -- including a paragraph telling people how to
upgrade from v0.4.5, under a heading naming a version they had not downloaded.
Four releases went out that way.

Notes now come from the tag's own annotation, which is where they are written,
with the evergreen download and verification guidance appended.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = (ROOT / ".github" / "workflows" / "build.yml").read_text()
NOTES_DIR = ROOT / ".github" / "release-notes"


def test_no_release_note_file_is_named_for_a_version():
    """A file named for one version will be served for every other."""

    named = [p.name for p in NOTES_DIR.glob("*.md") if re.search(r"v?\d+\.\d+\.\d+", p.name)]
    assert not named, (
        "these are named for a specific version and will go stale: {}".format(named)
    )


def test_the_body_comes_from_the_tag():
    assert "git tag -l --format='%(contents)'" in WORKFLOW, (
        "the notes are not read from the tag that is being released"
    )
    assert "body_path: /tmp/notes/body.md" in WORKFLOW


def test_a_tag_with_no_annotation_stops_the_release():
    """Silently publishing a release with empty notes is worse than failing."""

    assert 'has no annotation, so it has no notes' in WORKFLOW


def test_the_tag_object_is_actually_fetched():
    """A shallow checkout does not bring the annotation with it."""

    release = WORKFLOW.split("  release:", 1)[1].split("\n  pages:", 1)[0]
    assert "fetch-depth: 0" in release, (
        "the release checkout is shallow, so the tag annotation would be missing "
        "and every release would fail at the notes step"
    )


def test_the_evergreen_guidance_still_ships():
    kept = NOTES_DIR / "download-and-verify.md"
    assert kept.is_file()
    text = kept.read_text()
    for expected in ("Run anyway", "apple-silicon", "intel", "Checking what you downloaded"):
        assert expected in text, "{} is no longer explained to downloaders".format(expected)


def test_the_kept_guidance_names_no_specific_version():
    text = (NOTES_DIR / "download-and-verify.md").read_text()
    stale = re.findall(r"v0\.\d+\.\d+", text)
    assert not stale, "the evergreen notes still name versions: {}".format(sorted(set(stale)))
