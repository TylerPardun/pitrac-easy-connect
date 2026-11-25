"""Backup and restore.

Calibration is the thing worth protecting: Wi-Fi takes a minute to re-enter and
pairing takes one click, but calibration means setting up a rig again. These
tests are mostly about the ways a restore could quietly make things worse.
"""

import copy
import json
import pathlib
from unittest import mock

import pytest

from pitrac_easy_connect.common.configstore import ConfigStore
from pitrac_easy_connect.common.errors import EasyConnectError
from pitrac_easy_connect.common.identity import IdentityStore
from pitrac_easy_connect.models import Simulator
from pitrac_easy_connect.pi import backup as backup_module
from pitrac_easy_connect.pi.backup import (
    SECTION_CALIBRATION,
    SECTION_IDENTITY,
    SECTION_PAIRINGS,
    SECTION_PREFERENCES,
    BackupManager,
)
from pitrac_easy_connect.pi.pairing import PairingManager
from pitrac_fixture import make_pitrac

CALIBRATION = {
    "gs_config": {
        "cameras": {
            "kCamera1CalibrationMatrix": [["1833.5", "0.0", "697.2"]],
            "kCamera1FocalLength": "6.1",
            "kCamera1Angles": ["1.2", "-3.4"],
            "kCamera2CalibrationMatrix": [["2340.2", "0.0", "698.4"]],
            "kCamera2FocalLength": "6.2",
            "kCamera2Angles": ["0.8", "2.2"],
        }
    }
}


def build(tmp_path, name="a", serial="pi-same"):
    root = tmp_path / name
    root.mkdir(parents=True, exist_ok=True)
    identity = IdentityStore(root / "device.json")
    settings = ConfigStore(root / "settings.json", {"simulator": Simulator.GSPRO.value})
    pitrac = make_pitrac(root, relay_ports={Simulator.GSPRO: 9210, Simulator.E6: 9248})
    pitrac.api.calibration = copy.deepcopy(CALIBRATION)
    pairings = PairingManager(root / "pairings.json", identity.identity.device_id)
    manager = BackupManager(identity, settings, pitrac, pairings, root / "backups",
                            board_serial=lambda: serial)
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
    before = copy.deepcopy(pitrac.api.calibration)

    with pytest.raises(EasyConnectError):
        manager.restore(b'{"format":"pitrac-easy-connect-backup","formatVersion":1,'
                        b'"checksum":"wrong","payload":{"sections":["calibration"]}}')

    assert pitrac.api.calibration == before
    assert pitrac.snapshot().calibrated is True


# --- Restoring onto the same enclosure ------------------------------------


def test_calibration_can_be_restored_after_it_is_lost(tmp_path):
    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    backup = manager.create_bytes()

    pitrac.api.calibration = {}
    assert pitrac.snapshot().calibrated is False

    result = manager.restore(backup)
    assert SECTION_CALIBRATION in result.restored
    assert pitrac.snapshot().calibrated is True
    assert pitrac.api.calibration == CALIBRATION


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
    assert pitrac.snapshot().relay_target(9210).delivering is True
    assert pitrac.api.user_settings["gs_config"]["cameras"]["kCamera1Gain"] == 7


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
    # Everything by that name, not just the finished snapshots: each one holds
    # the whole enclosure's secrets, whatever its extension.
    assert len(list((tmp_path / "a" / "backups").glob("before-restore-*"))) <= 5


def test_restores_in_the_same_second_do_not_shove_a_snapshot_aside(tmp_path):
    """The stamp resolves to the second; two restores can share one.

    The atomic write keeps a .bak of whatever it replaces, so an overwritten
    snapshot used to survive as a second copy of the secrets under a name
    nothing pruned.
    """

    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    backup = manager.create_bytes()
    backups = tmp_path / "a" / "backups"

    with mock.patch.object(backup_module.time, "strftime", return_value="20260101-120000"):
        first = manager.restore(backup).pre_restore_backup
        second = manager.restore(backup).pre_restore_backup

    assert first != second, "one restore must not overwrite another's snapshot"
    assert list(backups.glob("*.bak")) == []
    assert sorted(path.name for path in backups.glob("before-restore-*")) == [
        "before-restore-20260101-120000-2.pitracbackup",
        "before-restore-20260101-120000.pitracbackup",
    ]


def test_debris_from_an_interrupted_write_is_cleared_away(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path)
    backups = tmp_path / "a" / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stray = backups / "before-restore-20200101-000000.pitracbackup.new"
    stray.write_text("half a snapshot, all of the secrets")

    manager.restore(manager.create_bytes())

    assert not stray.exists()


# --- Restoring onto a different enclosure ---------------------------------


def test_calibration_from_another_enclosure_is_refused_by_default(tmp_path):
    """Another enclosure's calibration yields plausible but wrong ball flight."""

    _a_identity, _a_settings, _a_pitrac, _a_pairings, first = build(tmp_path, "a")
    _b_identity, _b_settings, second_pitrac, _b_pairings, second = build(tmp_path, "b")
    second_pitrac.api.calibration = {}

    with pytest.raises(EasyConnectError) as caught:
        second.restore(first.create_bytes())
    assert caught.value.info.code == "PT-CFG-004"
    assert second_pitrac.snapshot().calibrated is False


def test_calibration_from_another_enclosure_can_be_forced_deliberately(tmp_path):
    _a_identity, _a_settings, _a_pitrac, _a_pairings, first = build(tmp_path, "a")
    _b_identity, _b_settings, second_pitrac, _b_pairings, second = build(tmp_path, "b")

    result = second.restore(first.create_bytes(), confirm_different_device=True)
    assert SECTION_CALIBRATION in result.restored
    assert second_pitrac.api.calibration == CALIBRATION


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
    new_pitrac.api.calibration = {}
    assert new_identity.identity.device_id != original.device_id

    result = rebuilt.restore(backup, identity=True, pairings=True)

    assert new_identity.identity.device_id == original.device_id
    assert new_identity.identity.setup_password == original.setup_password
    assert new_identity.identity.setup_ssid == original.setup_ssid, "the owner card still works"
    assert new_pitrac.snapshot().calibrated is True
    assert new_pairings.count == 1
    assert set(result.restored) >= {SECTION_CALIBRATION, SECTION_IDENTITY, SECTION_PAIRINGS}


def test_restoring_identity_makes_the_calibration_check_pass_quietly(tmp_path):
    _identity, _settings, _pitrac, _pairings, manager = build(tmp_path, "original")
    backup = manager.create_bytes(include_identity=True)

    _new_identity, _s, new_pitrac, _p, rebuilt = build(tmp_path, "rebuilt")
    new_pitrac.api.calibration = {}

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

    calibration_before = copy.deepcopy(pitrac.api.calibration)
    document["payload"]["identity"]["deviceId"] = "!!not a device id!!"
    from pitrac_easy_connect.pi.backup import checksum_of

    document["checksum"] = checksum_of(document["payload"])

    with pytest.raises(Exception):
        manager.restore(document, calibration=True, preferences=True, identity=True)

    assert pitrac.api.calibration == calibration_before, \
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


def test_a_failure_partway_through_a_restore_puts_everything_back(tmp_path, monkeypatch):
    """Calibration was written before preferences, identity and pairings. A
    failure after that first write left the new calibration installed."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    document = json.loads(manager.create_bytes().decode())

    # Change the calibration in the backup so a successful restore is visible.
    document["payload"]["calibration"] = {"gs_config": {"cameras": {"marker": "from-backup"}}}
    from pitrac_easy_connect.pi.backup import checksum_of

    document["checksum"] = checksum_of(document["payload"])

    before = copy.deepcopy(pitrac.api.calibration)

    def explode(*_args, **_kwargs):
        raise RuntimeError("the card filled up")

    monkeypatch.setattr(manager, "_restore_preferences", explode)
    with pytest.raises(Exception):
        manager.restore(document, calibration=True, preferences=True)

    assert pitrac.api.calibration == before, \
        "calibration was left changed by a restore that failed"


def test_restoring_actually_restores_a_pitrac_setting(tmp_path):
    """The merge let every current value override the backup, so restoring a
    backup made when a setting was 7 onto a machine set to 8 left it at 8 and
    reported success. Nothing in the suite noticed."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)

    pitrac.api.user_settings = {"gs_config": {"cameras": {"kCamera1Gain": 7}}}
    document = json.loads(manager.create_bytes().decode())

    # The machine has since been changed.
    pitrac.api.user_settings = {"gs_config": {"cameras": {"kCamera1Gain": 8}}}

    manager.restore(document, preferences=True)

    after = copy.deepcopy(pitrac.api.user_settings)
    assert after["gs_config"]["cameras"]["kCamera1Gain"] == 7, \
        "the backup's value should have been restored"


def test_a_restore_does_not_redirect_where_shots_are_sent(tmp_path):
    """That is this installation's own wiring, not a preference. PiTrac turns
    these keys into new simulators if they ever reappear in its settings."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    pitrac.api.user_settings = {
        "gs_config": {
            "cameras": {"kCamera1Gain": 7},
            "golf_simulator_interfaces": {"GSPro": {
                "kGSProConnectAddress": "10.9.9.9", "kGSProConnectPort": 1111}},
        },
        "simulators": {"gspro": {"host": "10.9.9.9", "enabled": True}},
    }
    document = json.loads(manager.create_bytes().decode())
    sims = pitrac.api.sims()

    manager.restore(document, preferences=True)

    assert pitrac.api.user_settings == {"gs_config": {"cameras": {"kCamera1Gain": 7}}}
    assert pitrac.api.sims() == sims, "the relay wiring stayed as this machine had it"


def test_a_failed_restore_puts_pitracs_own_settings_back_too(tmp_path, monkeypatch):
    """The rollback recorded Easy-Connect's preferences but not PiTrac's own
    settings file, which the same step writes. A failure afterwards left
    PiTrac changed while everything else was put back."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    pitrac.api.user_settings = {"gs_config": {"cameras": {"kCamera1Gain": 7}}}
    document = json.loads(manager.create_bytes(include_identity=True).decode())

    pitrac.api.user_settings = {"gs_config": {"cameras": {"kCamera1Gain": 8}}}
    before = copy.deepcopy(pitrac.api.user_settings)

    def explode(_section):
        raise RuntimeError("the identity section is corrupt")

    monkeypatch.setattr(manager.identity_store, "restore", explode)
    with pytest.raises(Exception):
        manager.restore(document, preferences=True, identity=True,
                        confirm_different_device=True)

    assert pitrac.api.user_settings == before, \
        "PiTrac's settings were left changed by a restore that failed"


def test_restoring_an_identity_updates_the_pairing_manager_immediately(tmp_path):
    """The pairing manager captured the device id when it was built. Left
    stale, pairings are checked against an enclosure that no longer exists
    until the service restarts."""

    _identity, _settings, _pitrac, pairings, manager = build(tmp_path)
    document = json.loads(manager.create_bytes(include_identity=True).decode())

    original = pairings.device_id
    document["payload"]["identity"]["deviceId"] = "ZZZZ9999"
    from pitrac_easy_connect.pi.backup import checksum_of

    document["checksum"] = checksum_of(document["payload"])

    manager.restore(document, identity=True, confirm_different_device=True)

    assert pairings.device_id == "ZZZZ9999"
    assert pairings.device_id != original


# --- What a failed restore has to put back ---------------------------------


def test_a_rolled_back_identity_takes_the_pairing_manager_with_it(tmp_path):
    """Otherwise pairings are checked against an enclosure that was abandoned.

    Restoring the identity forward updates the pairing manager. Rolling it
    back did not, so a restore that failed part way left the two disagreeing
    about which enclosure this is until the service happened to restart.
    """

    identity, _settings, _pitrac, pairings, manager = build(tmp_path)
    original = identity.identity.device_id
    assert pairings.device_id == original

    state = manager._remember({}, calibration=False, preferences=False,
                              identity=True, pairings=False)

    # Something else takes the enclosure's identity over, as a restore does.
    other = dict(identity.identity.as_dict(include_secrets=True))
    other["deviceId"] = "ZZZZ2345"
    identity.restore(other)
    pairings.device_id = "ZZZZ2345"

    manager._put_back(state)

    assert identity.identity.device_id == original
    assert pairings.device_id == original, "the pairing manager was left on the abandoned id"


# --- What PiTrac will not allow ---------------------------------------------


def test_a_backup_is_refused_rather_than_made_without_calibration(tmp_path):
    """It would look complete until the day it was needed."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    pitrac.api.reachable = False
    with pytest.raises(EasyConnectError) as caught:
        manager.create()
    assert caught.value.info.code == "PT-CFG-009"


def test_a_restore_that_cannot_reach_pitrac_changes_nothing(tmp_path):
    identity, settings, pitrac, _pairings, manager = build(tmp_path)
    identity.rename("Garage Bay")
    backup = manager.create_bytes()
    identity.rename("Something Else")

    pitrac.api.reachable = False
    with pytest.raises(EasyConnectError) as caught:
        manager.restore(backup)
    assert caught.value.info.code == "PT-CFG-009"
    assert identity.identity.display_name == "Something Else"


def test_the_paired_computers_can_be_restored_without_pitrac(tmp_path):
    _identity, _settings, pitrac, pairings, manager = build(tmp_path)
    pairings.create_pairing("Sim PC")
    backup = manager.create_bytes(include_pairings=True)
    pairings.revoke_all()

    pitrac.api.reachable = False
    result = manager.restore(backup, calibration=False, preferences=False, pairings=True)
    assert pairings.count == 1
    assert result.restored == [SECTION_PAIRINGS]


def test_calibration_pitrac_partly_refuses_is_put_back_as_it_was(tmp_path):
    """Part of a calibration is not a calibration."""

    _identity, _settings, pitrac, _pairings, manager = build(tmp_path)
    backup = manager.create_bytes()
    pitrac.api.calibration = {"gs_config": {"cameras": {"marker": "newer"}}}
    real = pitrac.api.import_config

    def refuse_once(document):
        pitrac.api.import_config = real
        real(document)
        return {"gs_config.cameras.kCamera1Angles": "must be an array"}

    pitrac.api.import_config = refuse_once
    with pytest.raises(EasyConnectError) as caught:
        manager.restore(backup)
    assert caught.value.info.code == "PT-CFG-010"
    assert pitrac.api.calibration == {"gs_config": {"cameras": {"marker": "newer"}}}


# --- The strobe, which the wrong settings can damage -------------------------


def strobe(pitrac, where="calibration"):
    held = pitrac.api.calibration if where == "calibration" else pitrac.api.user_settings
    return (held.get("gs_config") or {}).get("strobing")


def set_strobe(pitrac, drive, board="3"):
    pitrac.api.calibration.setdefault("gs_config", {})["strobing"] = {"kDAC_setting": drive}
    pitrac.api.user_settings.setdefault("gs_config", {})["strobing"] = {
        "kConnectionBoardVersion": board}


MINE = ({"kDAC_setting": 90}, {"kConnectionBoardVersion": "3"})


def two_machines(tmp_path):
    first = build(tmp_path, "a", serial="pi-a")
    second = build(tmp_path, "b", serial="pi-b")
    set_strobe(first[2], 200, board="2")
    set_strobe(second[2], 90, board="3")
    return first, second


@pytest.mark.parametrize("options", [
    {"confirm_different_device": True},
    {"confirm_different_device": True, "identity": True},
    {"confirm_different_device": True, "confirm_same_board": True},
    {"confirm_different_device": True, "identity": True, "confirm_same_board": True},
])
def test_another_boards_strobe_settings_are_never_taken(tmp_path, options):
    """However it is asked for, and whichever section they are hiding in. The
    board version is one of them: an older one switches PiTrac's check off."""

    first, second = two_machines(tmp_path)
    result = second[4].restore(first[4].create_bytes(include_identity=True), **options)
    assert (strobe(second[2]), strobe(second[2], "settings")) == MINE
    assert result.strobe_restored is False


def test_sharing_an_identity_does_not_make_them_the_same_board(tmp_path):
    """Restoring identity copies it, so afterwards every later restore looked
    like one onto the same enclosure."""

    first, second = two_machines(tmp_path)
    backup = first[4].create_bytes(include_identity=True)
    second[4].restore(backup, identity=True, confirm_different_device=True)
    assert second[4].inspect(backup).same_device is True
    second[4].restore(backup, confirm_different_device=True, confirm_same_board=True)
    assert (strobe(second[2]), strobe(second[2], "settings")) == MINE


def test_sharing_an_identity_does_not_make_the_cameras_the_same_either(tmp_path):
    first, second = two_machines(tmp_path)
    backup = first[4].create_bytes(include_identity=True)
    with pytest.raises(EasyConnectError) as caught:
        second[4].restore(backup, identity=True)
    assert caught.value.info.code == "PT-CFG-004"


def test_a_machine_with_no_strobe_settings_is_left_without_any(tmp_path):
    """PiTrac then refuses to fire it until it is calibrated, which is right."""

    first, second = two_machines(tmp_path)
    second[2].api.calibration = {}
    second[2].api.user_settings = {}
    second[4].restore(first[4].create_bytes(), confirm_different_device=True)
    assert strobe(second[2]) is None and strobe(second[2], "settings") is None


def test_a_new_memory_card_gets_them_back_when_the_owner_says_so(tmp_path):
    """What the backup is for: the same Pi, the same board, a new card."""

    before = build(tmp_path, "before", serial="pi-a")
    set_strobe(before[2], 200)
    backup = before[4].create_bytes(include_identity=True)
    after = build(tmp_path, "after", serial="pi-a")
    after[2].api.calibration = {}

    assert after[4].inspect(backup).can_restore_strobe is True
    result = after[4].restore(backup, identity=True, confirm_same_board=True)
    assert strobe(after[2]) == {"kDAC_setting": 200}
    assert result.strobe_restored is True


def test_the_same_pi_is_not_enough_without_the_owners_word(tmp_path):
    """Only they know whether the board plugged into it was changed."""

    before = build(tmp_path, "a", serial="pi-a")
    set_strobe(before[2], 200)
    backup = before[4].create_bytes()
    set_strobe(before[2], 90)
    before[4].restore(backup)
    assert strobe(before[2]) == {"kDAC_setting": 90}


@pytest.mark.parametrize("theirs, ours", [("", "pi-a"), ("pi-a", ""), ("", "")])
def test_not_knowing_which_pi_it_was_is_not_knowing(tmp_path, theirs, ours):
    """Including every backup made before this was recorded."""

    before = build(tmp_path, "a", serial=theirs)
    set_strobe(before[2], 200)
    backup = before[4].create_bytes(include_identity=True)
    after = build(tmp_path, "b", serial=ours)
    set_strobe(after[2], 90)
    info = after[4].inspect(backup)
    assert info.same_hardware is None and info.can_restore_strobe is False
    after[4].restore(backup, identity=True, confirm_same_board=True)
    assert strobe(after[2]) == {"kDAC_setting": 90}


def test_the_owner_is_asked_and_the_safe_answer_is_no():
    from pitrac_easy_connect.companion.page import PAGE as desktop
    from pitrac_easy_connect.pi.portal_page import PAGE as portal

    for page in (desktop, portal):
        assert "info.canRestoreStrobe && confirm(" in page
        assert "Cancel keeps the settings" in page


def test_a_pi_with_no_serial_number_is_not_given_one(tmp_path, monkeypatch):
    from pitrac_easy_connect.pi import nmcli_backend

    for text, expected in (("10000000abcdef01\x00", "10000000abcdef01"), ("0000000000000000\x00", ""), ("", "")):
        monkeypatch.setattr(nmcli_backend, "_read_text", lambda path: text)
        assert nmcli_backend.NmcliBackend().board_serial() == expected
