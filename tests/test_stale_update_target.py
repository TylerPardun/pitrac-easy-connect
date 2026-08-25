"""A saved update target the desktop has already passed is finished.

When a coordinated update starts, the version both halves should reach is
saved, so the plan survives the link dropping while the enclosure restarts.
It was only ever cleared on success.

Install a newer desktop by hand -- which is exactly what someone does when
automatic installation has been refused -- and the saved target is now behind
the running app. That was treated as a blocking fault:

    This desktop (0.6.0) is newer than the saved update target (0.5.0).
    Start a new update check before changing PiTrac.

Nothing was wrong. The plan was simply spent, and holding it stopped the
enclosure being offered the update it was actually due. The rule worth
keeping is the opposite case: an *older* desktop must never push the
enclosure ahead of itself.
"""

import pytest

from pitrac_easy_connect.common.updates import UpdateStatus, coordinate_update


def status(installed, latest):
    return UpdateStatus(installed, "packaged", latest=latest, available=installed != latest,
                        can_apply=True, detail="", download_url="https://example.invalid")


def test_a_target_the_desktop_has_passed_does_not_block_the_enclosure():
    """The enclosure is behind and should be offered the update."""

    plan = coordinate_update(status("0.6.0", "0.6.0"), enclosure_version="0.4.6",
                             pending_target="0.5.0")
    assert plan.phase == "pi-update-required", plan.detail
    assert plan.can_update_pi is True
    assert "0.6.0" in plan.detail


def test_the_spent_target_is_reported_so_it_can_be_forgotten():
    """Otherwise it is re-read on the next check and blocks again."""

    plan = coordinate_update(status("0.6.0", "0.6.0"), enclosure_version="0.4.6",
                             pending_target="0.5.0")
    assert plan.discard_pending is True
    assert plan.as_dict()["discardPending"] is True


def test_an_older_desktop_still_may_not_push_the_enclosure_ahead():
    """The safety this must not lose."""

    plan = coordinate_update(status("0.4.9", "0.6.0"), enclosure_version="0.4.6",
                             pending_target="0.6.0")
    assert plan.phase == "desktop-update-required"
    assert plan.can_update_pi is False


def test_a_target_still_ahead_is_kept():
    plan = coordinate_update(status("0.6.0", "0.6.0"), enclosure_version="0.4.6",
                             pending_target="0.6.0")
    assert plan.phase == "pi-update-required"
    assert plan.discard_pending is False


def test_matching_versions_are_synchronized():
    plan = coordinate_update(status("0.6.0", "0.6.0"), enclosure_version="0.6.0",
                             pending_target="0.6.0")
    assert plan.synchronized is True


def test_nothing_user_facing_says_saved_update_target():
    """Internal vocabulary, in a sentence the owner is asked to act on."""

    import inspect

    source = inspect.getsource(coordinate_update)
    assert "saved update target" not in source, (
        "the phrase describes bookkeeping the owner never set up and cannot see"
    )


def test_the_service_forgets_an_overtaken_plan(tmp_path, monkeypatch):
    """Otherwise it is read again on the next check and blocks again."""

    from pitrac_easy_connect.companion.service import CompanionService

    service = CompanionService(config_path=tmp_path / "companion.json", discovery_port=0,
                               search_seconds=0.05, research_seconds=0.05)
    try:
        service._remember_update_target("0.5.0")
        assert service.store.get("updateTarget") == "0.5.0"

        # A check where this desktop is already past that target.
        monkeypatch.setattr(service, "version", "0.6.0", raising=False)
        monkeypatch.setattr(
            service, "_last_desktop_status",
            UpdateStatus("0.6.0", "packaged", latest="0.6.0", detail=""),
            raising=False,
        )
        service._update_status()

        assert service.store.get("updateTarget") in ("", None), (
            "the overtaken plan is still saved, so the next check blocks again"
        )
    finally:
        service.close()
