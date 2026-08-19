import json
import os

import pytest

from pitrac_easy_connect.common.configstore import ConfigStore, atomic_write_bytes
from pitrac_easy_connect.common.errors import EasyConnectError


def test_values_survive_a_reload(tmp_path):
    path = tmp_path / "settings.json"
    store = ConfigStore(path, {"simulator": "gspro"})
    store.set("simulator", "e6")
    assert ConfigStore(path, {"simulator": "gspro"}).get("simulator") == "e6"


def test_defaults_fill_in_keys_a_newer_build_added(tmp_path):
    path = tmp_path / "settings.json"
    ConfigStore(path, {"simulator": "gspro"}).set("simulator", "e6")
    reopened = ConfigStore(path, {"simulator": "gspro", "directMode": False})
    assert reopened.get("simulator") == "e6"
    assert reopened.get("directMode") is False


def test_a_damaged_document_falls_back_to_the_backup(tmp_path):
    path = tmp_path / "settings.json"
    store = ConfigStore(path, {"simulator": "gspro"})
    store.set("simulator", "e6")
    store.set("simulator", "gspro")
    # The backup now holds the "e6" document. Damage the live one.
    path.write_text("{ this is not json")

    recovered = ConfigStore(path, {"simulator": "gspro"})
    assert recovered.get("simulator") == "e6"
    assert recovered.recovered_from_backup is True
    assert recovered.corruption_error().info.code == "PT-PI-009"


def test_no_usable_document_anywhere_gives_defaults_not_a_crash(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text("garbage")
    store = ConfigStore(path, {"simulator": "gspro"})
    assert store.get("simulator") == "gspro"


def test_a_newer_schema_is_refused_rather_than_downgraded(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schemaVersion": 9, "data": {"simulator": "e6"}}))
    with pytest.raises(EasyConnectError) as caught:
        ConfigStore(path, {"simulator": "gspro"}, schema_version=2)
    assert caught.value.info.code == "PT-CFG-002"


def test_migrations_run_in_order_up_to_the_current_version(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"schemaVersion": 1, "data": {"sim": "e6"}}))

    def to_v2(data):
        return {"simulator": data.pop("sim"), **data}

    def to_v3(data):
        data["simulatorChosenBy"] = "migration"
        return data

    store = ConfigStore(
        path,
        {"simulator": "gspro", "simulatorChosenBy": "default"},
        schema_version=3,
        migrations={1: to_v2, 2: to_v3},
    )
    assert store.get("simulator") == "e6"
    assert store.get("simulatorChosenBy") == "migration"


def test_secret_documents_are_not_world_readable(tmp_path):
    path = tmp_path / "pairings.json"
    ConfigStore(path, {"pairings": []}, secret=True).set("pairings", ["a"])
    assert os.stat(path).st_mode & 0o077 == 0


def test_an_interrupted_write_leaves_a_readable_document(tmp_path):
    # Simulate the power failing after the temporary file is written but before
    # the rename. The live document must still be the previous valid one.
    path = tmp_path / "settings.json"
    store = ConfigStore(path, {"simulator": "gspro"})
    store.set("simulator", "e6")

    (path.with_name(path.name + ".new")).write_text('{"schemaVersion": 1, "data": {"sim')

    assert ConfigStore(path, {"simulator": "gspro"}).get("simulator") == "e6"


def test_atomic_write_replaces_content_completely(tmp_path):
    path = tmp_path / "file.bin"
    atomic_write_bytes(path, b"a much longer first version")
    atomic_write_bytes(path, b"short")
    assert path.read_bytes() == b"short"
    assert path.with_name("file.bin.bak").read_bytes() == b"a much longer first version"
