"""The frozen app must not inherit a CA path from the build machine."""

import importlib.util
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENTRY = ROOT / "packaging" / "app_entry.py"
SPEC = ROOT / "packaging" / "PiTrac-Easy-Connect.spec"


def load_entry(monkeypatch, ca_path):
    certifi = types.ModuleType("certifi")
    certifi.where = lambda: ca_path

    class AppModule(types.ModuleType):
        def __getattribute__(self, name):
            if name == "main":
                assert os.environ.get("SSL_CERT_FILE")
            return super().__getattribute__(name)

    app = AppModule("pitrac_easy_connect.companion.app")
    app.main = lambda _args: 0
    monkeypatch.setitem(sys.modules, "certifi", certifi)
    monkeypatch.setitem(sys.modules, "pitrac_easy_connect.companion.app", app)
    spec = importlib.util.spec_from_file_location("packaged_app_entry_test", ENTRY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_packaged_entry_selects_the_ca_store_before_application_import(monkeypatch):
    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    load_entry(monkeypatch, "/inside/the/app/certifi/cacert.pem")
    assert os.environ["SSL_CERT_FILE"] == "/inside/the/app/certifi/cacert.pem"


def test_an_explicit_administrator_ca_override_is_preserved(monkeypatch):
    monkeypatch.setenv("SSL_CERT_FILE", "/managed/company-ca.pem")
    load_entry(monkeypatch, "/inside/the/app/certifi/cacert.pem")
    assert os.environ["SSL_CERT_FILE"] == "/managed/company-ca.pem"


def test_the_frozen_app_explicitly_carries_certifis_ca_file():
    source = SPEC.read_text(encoding="utf-8")
    assert '(certifi.where(), "certifi")' in source


def test_certifi_is_an_exact_build_pin():
    requirements = (ROOT / "packaging" / "build-requirements.txt").read_text()
    lines = [line.strip() for line in requirements.splitlines()]
    matches = [line for line in lines if line.startswith("certifi==")]
    assert matches == ["certifi==2026.7.22"]
