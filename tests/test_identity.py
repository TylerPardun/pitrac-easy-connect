from pitrac_easy_connect.common.identity import (
    DEVICE_ID_LENGTH,
    IdentityStore,
    new_device_id,
    new_setup_password,
)


def test_identity_is_created_once_and_never_changes(tmp_path):
    path = tmp_path / "device.json"
    first = IdentityStore(path).identity
    second = IdentityStore(path).identity
    assert first == second
    assert len(first.device_id) == DEVICE_ID_LENGTH


def test_two_enclosures_do_not_collide():
    ids = {new_device_id() for _ in range(500)}
    assert len(ids) == 500


def test_device_id_avoids_characters_people_misread():
    for _ in range(200):
        assert not set(new_device_id()) & set("O0I1L")


def test_setup_password_is_long_enough_for_wpa2():
    for _ in range(50):
        assert len(new_setup_password()) >= 8


def test_hostname_and_ssid_are_derived_from_the_device_id(tmp_path):
    identity = IdentityStore(tmp_path / "device.json").identity
    assert identity.setup_ssid == "PiTrac-{}".format(identity.device_id)
    assert identity.hostname == "pitrac-{}".format(identity.device_id.lower())
    assert identity.short_id == identity.device_id[-4:]


def test_the_public_view_never_leaks_the_setup_password(tmp_path):
    identity = IdentityStore(tmp_path / "device.json").identity
    assert "setupPassword" not in identity.as_dict()
    assert identity.as_dict(include_secrets=True)["setupPassword"] == identity.setup_password


def test_the_owner_card_carries_everything_needed_to_get_back_in(tmp_path):
    identity = IdentityStore(tmp_path / "device.json").identity
    card = identity.owner_card()
    assert identity.setup_ssid in card
    assert identity.setup_password in card
    assert identity.recovery_address in card


def test_renaming_keeps_the_device_id(tmp_path):
    store = IdentityStore(tmp_path / "device.json")
    original = store.identity.device_id
    renamed = store.rename("  Garage   Bay  ")
    assert renamed.display_name == "Garage Bay"
    assert renamed.device_id == original


def test_a_regenerated_setup_password_replaces_the_old_one(tmp_path):
    store = IdentityStore(tmp_path / "device.json")
    before = store.identity.setup_password
    assert store.regenerate_setup_password().setup_password != before
