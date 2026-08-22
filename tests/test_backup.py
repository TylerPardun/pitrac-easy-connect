import pathlib
"""Backup and restore.

Calibration is the thing worth protecting: Wi-Fi takes a minute to re-enter and a
pairing code takes seconds, but calibration means setting up a rig again. These
tests are mostly about the ways a restore could quietly make things worse.
"""

import json

import pytest

from pitrac_easy_connect.common.configstore import ConfigStore
from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.common.identity import IdentityStore
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi.backup import (
    SECTION_CALIBRATION,
    SECTION_IDENTITY,
    SECTION_PAIRINGS,
    SECTION_PREFERENCES,
    BackupManager,
)
from pitrac_easy_connect.pi.pairing import PairingManager
from pitrac_easy_connect.pi.pitrac import PitracInstallation

CALIBRATION = {
    "gs_config": {
        "cameras": {
            "kCamera1CalibrationMatrix": [["1833.5", "0.0", "697.2"]],
            "kCamera2CalibrationMatrix": [["2340.2", "0.0", "698.4"]],
        }
    }
}


def build(tmp_path, name="a"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    identity = IdentityStore(root / "device.json")
    settings = ConfigStore(root / "settings.json", {"simulator": Simulator.GSPRO.value})
    pitrac = PitracInstallation(root / "user_settings.json", root / "calibration_data.json")
    pitrac.calibration_path.write_text(json.dumps(CALIBRATION))
    pitrac.point_at_relay({Simulator.GSPRO: 9210, Simulator.E6: 9248})
    pairings = PairingManager(root / "pairings.json", identity.identity.device_id)
    manager = BackupManager(identity, settings, pitrac, pairings, root / "backups")
    return identity, settings, pitrac, pairings, manager


# --- What goes in a backup ------------------------------------------------


def test_a_backup_carries_calibration_and_preferences(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    info = manager.inspect(manager.create_bytes())
    assert SECTION_CALIBRATION in info.sections
    assert SECTION_PREFERENCES in info.sections


def test_secrets_are_left_out_unless_asked_for(tmp_path):
    identity, _settings, _pitrac, pairings, manager = build(tmp_path)
    pairings.create_pairing("Sim PC")

    plain = manager.create_bytes()
    assert identity.identity.setup_password.encode() not in plain
    assert b"secret" not in plain.lower() or SECTION_PAIRINGS.encode() not in plain

    info = manager.inspect(plain)
    assert info.contains_secrets is False
    assert SECTION_IDENTITY not in info.sections
    assert SECTION_PAIRINGS not in info.sections


def test_secrets_are_included_when_explicitly_requested(tmp_path):
    identity, _settings, _pitrac, pairings, manager = build(tmp_path)
    pairings.create_pairing("Sim PC")

    full = manager.create_bytes(include_identity=True, include_pairings=True)
    info = manager.inspect(full)
    assert info.contains_secrets is True
    assert identity.identity.setup_password.encode() in full


def test_a_backup_names_the_enclosure_it_came_from(tmp_path):
    identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    info = manager.inspect(manager.create_bytes())
    assert info.device_id == identity.identity.device_id
    assert info.display_name == identity.identity.display_name
    assert info.created_text


def test_the_suggested_filename_identifies_the_enclosure(tmp_path):
    identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    assert identity.identity.device_id.lower() in manager.suggested_filename()


# --- Refusing bad backups -------------------------------------------------


def test_an_edited_backup_is_refused(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    document = manager.create()
    document["payload"][SECTION_CALIBRATION]["gs_config"]["cameras"][
        "kCamera1CalibrationMatrix"
    ] = [["999", "0", "0"]]

    with pytest.raises(EasyConnectError) as caught:
        manager.inspect(json.dumps(document))
    assert caught.value.info.code == "PT-CFG-003"


def test_a_truncated_backup_is_refused(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    truncated = manager.create_bytes()[: 200]
    with pytest.raises(EasyConnectError) as caught:
        manager.inspect(truncated)
    assert caught.value.info.code == "PT-CFG-003"


@pytest.mark.parametrize(
    "rubbish",
    [b"", b"not json", b"[]", b'{"format":"something-else"}', b'{"hello":"world"}'],
)
def test_a_file_that_is_not_a_backup_is_refused(tmp_path, rubbish):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        manager.inspect(rubbish)
    assert caught.value.info.code in ("PT-CFG-003", "PT-CFG-002")


def test_a_backup_from_a_newer_build_is_refused_not_guessed_at(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    document = manager.create()
    document["formatVersion"] = 99
    with pytest.raises(EasyConnectError) as caught:
        manager.inspect(json.dumps(document))
    assert caught.value.info.code == "PT-CFG-002"


def test_an_enormous_file_is_refused_before_it_is_parsed(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    with pytest.raises(EasyConnectError) as caught:
        manager.inspect(b"x" * (9 * 1024 * 1024))
    assert caught.value.info.code == "PT-CFG-003"


def test_a_corrupt_backup_cannot_overwrite_working_calibration(tmp_path):
    """The acceptance criterion: a bad backup leaves the good data alone."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    before = pitrac.read_calibration()

    with pytest.raises(EasyConnectError):
        manager.restore(b'{"format":"pitrac-easy-connect-backup","formatVersion":1,'
                        b'"checksum":"wrong","payload":{"sections":["calibration"]}}')

    assert pitrac.read_calibration() == before
    assert pitrac.is_calibrated() is True


# --- Restoring onto the same enclosure ------------------------------------


def test_calibration_can_be_restored_after_it_is_lost(tmp_path):
    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    backup = manager.create_bytes()

    pitrac.calibration_path.unlink()
    assert pitrac.is_calibrated() is False

    result = manager.restore(backup)
    assert SECTION_CALIBRATION in result.restored
    assert pitrac.is_calibrated() is True
    assert pitrac.read_calibration() == CALIBRATION


def test_preferences_come_back_too(tmp_path):
    identity, settings, _pitrac, _pairings, manager = build(tmp_path)
    settings.set("simulator", Simulator.E6.value)
    identity.rename("Garage Bay")
    backup = manager.create_bytes()

    settings.set("simulator", Simulator.GSPRO.value)
    identity.rename("Something Else")

    manager.restore(backup)
    assert settings.get("simulator") == Simulator.E6.value
    assert identity.identity.display_name == "Garage Bay"


def test_restoring_keeps_the_relay_pointers_this_build_wrote(tmp_path):
    """A backup made before the relay existed must not un-point PiTrac."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    document = manager.create()
    # Simulate an older backup whose PiTrac settings knew nothing about the relay.
    document["payload"][SECTION_PREFERENCES]["pitracSettings"] = {
        "gs_config": {"cameras": {"kCamera1Gain": 7}}
    }
    from pitrac_easy_connect.pi.backup import checksum_of

    from pitrac_easy_connect.pi.backup import checksum_of

    document["checksum"] = checksum_of(document["payload"])

    manager.restore(json.dumps(document))
    assert pitrac.points_at_relay({Simulator.GSPRO: 9210, Simulator.E6: 9248}) is True
    settings, _readable = pitrac.read_settings()
    assert settings["gs_config"]["cameras"]["kCamera1Gain"] == 7


def test_a_restore_takes_a_snapshot_first(tmp_path):
    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    backup = manager.create_bytes()
    result = manager.restore(backup)

    assert result.pre_restore_backup, "a restore must be undoable"
    snapshot = json.loads(open(result.pre_restore_backup).read())
    assert snapshot["format"] == "pitrac-easy-connect-backup"


def test_snapshots_do_not_pile_up_forever(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    backup = manager.create_bytes()
    for _ in range(9):
        manager.restore(backup)
    assert len(list((tmp_path / "a" / "backups").glob("before-restore-*"))) <= 5


# --- Restoring onto a different enclosure ---------------------------------


def test_calibration_from_another_enclosure_is_refused_by_default(tmp_path):
    """Another enclosure's calibration yields plausible but wrong ball flight."""

    _a_identity, _a_settings, _a_pitrac, _a_pairings, first = build(tmp_path, "a")
    _b_identity, _b_settings, second_pitrac, _b_pairings, second = build(tmp_path, "b")
    second_pitrac.calibration_path.unlink()

    with pytest.raises(EasyConnectError) as caught:
        second.restore(first.create_bytes())
    assert caught.value.info.code == "PT-CFG-004"
    assert second_pitrac.is_calibrated() is False


def test_calibration_from_another_enclosure_can_be_forced_deliberately(tmp_path):
    _a_identity, _a_settings, _a_pitrac, _a_pairings, first = build(tmp_path, "a")
    _b_identity, _b_settings, second_pitrac, _b_pairings, second = build(tmp_path, "b")

    result = second.restore(first.create_bytes(), confirm_different_device=True)
    assert SECTION_CALIBRATION in result.restored
    assert second_pitrac.read_calibration() == CALIBRATION


def test_preferences_alone_restore_without_the_device_warning(tmp_path):
    _a_identity, _a_settings, _a_pitrac, _a_pairings, first = build(tmp_path, "a")
    _b_identity, second_settings, _b_pitrac, _b_pairings, second = build(tmp_path, "b")
    second_settings.set("simulator", Simulator.GSPRO.value)

    result = second.restore(first.create_bytes(), calibration=False)
    assert SECTION_PREFERENCES in result.restored


# --- Replacing the memory card --------------------------------------------


def test_a_rebuilt_card_can_become_the_same_enclosure_again(tmp_path):
    """The case the backup exists for: same enclosure, new memory card.

    A fresh card generates a new device ID, so without restoring identity the
    enclosure would look like a different one and the printed owner card would
    be wrong.
    """

    identity, _settings, _pitrac, pairings, manager = build(tmp_path, "original")
    pairings.create_pairing("Sim Room PC")
    original = identity.identity
    backup = manager.create_bytes(include_identity=True, include_pairings=True)

    # A fresh installation: new identity, no calibration, nothing paired.
    new_identity, _s, new_pitrac, new_pairings, rebuilt = build(tmp_path, "rebuilt")
    new_pitrac.calibration_path.unlink()
    assert new_identity.identity.device_id != original.device_id

    result = rebuilt.restore(backup, identity=True, pairings=True)

    assert new_identity.identity.device_id == original.device_id
    assert new_identity.identity.setup_password == original.setup_password
    assert new_identity.identity.setup_ssid == original.setup_ssid, "the owner card still works"
    assert new_pitrac.is_calibrated() is True
    assert new_pairings.count == 1
    assert set(result.restored) >= {SECTION_CALIBRATION, SECTION_IDENTITY, SECTION_PAIRINGS}


def test_restoring_identity_makes_the_calibration_check_pass_quietly(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path, "original")
    backup = manager.create_bytes(include_identity=True)

    _new_identity, _s, new_pitrac, _p, rebuilt = build(tmp_path, "rebuilt")
    new_pitrac.calibration_path.unlink()

    # No confirm_different_device needed: restoring identity means it is the
    # same enclosure, so the calibration belongs to it.
    result = rebuilt.restore(backup, identity=True)
    assert SECTION_CALIBRATION in result.restored


def test_a_broken_identity_section_changes_nothing(tmp_path):
    identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    document = manager.create(include_identity=True)
    document["payload"][SECTION_IDENTITY]["setupPassword"] = "short"
    from pitrac_easy_connect.pi.backup import checksum_of

    from pitrac_easy_connect.pi.backup import checksum_of

    document["checksum"] = checksum_of(document["payload"])
    before = identity.identity

    with pytest.raises(ValueError):
        manager.restore(json.dumps(document), identity=True)
    assert identity.identity.setup_password == before.setup_password


def test_sections_that_are_absent_are_reported_as_skipped(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    backup = manager.create_bytes()  # no identity, no pairings
    result = manager.restore(backup, identity=True, pairings=True)
    assert SECTION_IDENTITY in result.skipped
    assert SECTION_PAIRINGS in result.skipped


def test_a_bad_identity_stops_the_restore_before_anything_changes(tmp_path):
    """Sections used to be checked as they were applied, so a backup with good
    calibration and a bad identity rewrote calibration and settings and then
    raised, leaving the enclosure half restored."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    document = json.loads(manager.create_bytes(include_identity=True).decode())

    calibration_before = pitrac.calibration_path.read_text()
    document["payload"]["identity"]["deviceId"] = "!!not a device id!!"
    from pitrac_easy_connect.pi.backup import checksum_of

    document["checksum"] = checksum_of(document["payload"])

    with pytest.raises(Exception):
        manager.restore(document, calibration=True, preferences=True, identity=True)

    assert pitrac.calibration_path.read_text() == calibration_before, \
        "calibration must not have been written before the identity was checked"


def test_the_undo_file_can_restore_the_paired_computers(tmp_path):
    """The snapshot advertised as an undo omitted pairings, so a restore that
    replaced the paired computers could not actually be reversed."""

    _identity, _settings, _pitrac, pairings, manager = build(tmp_path)
    original = pairings.create_pairing("The original PC").pairing_id

    document = json.loads(manager.create_bytes(include_pairings=True).decode())
    result = manager.restore(document, pairings=True)

    snapshot = json.loads(pathlib.Path(result.pre_restore_backup).read_text())
    assert "pairings" in snapshot["payload"], "the undo file must carry them"
    assert original in json.dumps(snapshot["payload"]["pairings"])
