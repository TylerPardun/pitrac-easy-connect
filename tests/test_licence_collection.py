"""The build refuses to ship a bundled component whose licence it cannot find.

That strictness is the point, so the ways a licence *is* legitimately found
have to keep working. Windows bundles two packages that ship no licence file
and name their author only in the modern combined address field; when that
went unread the release build stopped with nothing to distribute.
"""

import email.message
import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "packaging" / "collect-licences.py"


@pytest.fixture(scope="module")
def collector():
    spec = importlib.util.spec_from_file_location("collect_licences", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FakeDistribution:
    """Just enough of importlib.metadata's distribution to exercise lookup."""

    def __init__(self, files=None, **headers):
        self.metadata = email.message.Message()
        for field, value in headers.items():
            self.metadata[field.replace("_", "-")] = value
        self.files = files or []

    def read_text(self, name):
        return None

    def locate_file(self, name):
        return None


def test_a_bare_author_is_the_holder(collector):
    dist = FakeDistribution(Author="Ada Lovelace")
    assert collector.declared_holder(dist) == "Ada Lovelace"


def test_a_name_folded_into_the_address_field_is_the_holder(collector):
    # The form pythonnet and clr_loader actually use.
    dist = FakeDistribution(Author_email='"Benedikt Reinartz" <filmor@gmail.com>')
    assert collector.declared_holder(dist) == "Benedikt Reinartz"


def test_the_address_alone_is_not_a_holder(collector):
    dist = FakeDistribution(Author_email="someone@example.com")
    assert collector.declared_holder(dist) is None


def test_a_maintainer_stands_in_for_a_missing_author(collector):
    dist = FakeDistribution(Maintainer="Grace Hopper")
    assert collector.declared_holder(dist) == "Grace Hopper"


def test_a_wheel_with_no_licence_file_gets_the_declared_licence_in_full(collector):
    dist = FakeDistribution(
        License="MIT",
        Author_email='"The Contributors of the Python.NET Project" <pythonnet@python.org>',
    )
    text = collector.reconstructed_text(dist)
    assert "The Contributors of the Python.NET Project" in text
    assert "WITHOUT WARRANTY OF ANY KIND" in text
    # The reader is told the text was supplied rather than shipped.
    assert "ships no licence file" in text


def test_an_unknown_licence_is_never_guessed_at(collector):
    dist = FakeDistribution(License="Some-Bespoke-Licence-2.0", Author="Ada Lovelace")
    assert collector.reconstructed_text(dist) is None


def test_a_known_licence_with_nobody_to_credit_is_not_reconstructed(collector):
    dist = FakeDistribution(License="MIT")
    assert collector.reconstructed_text(dist) is None


def test_an_spdx_identifier_in_metadata_is_not_mistaken_for_a_licence(collector):
    dist = FakeDistribution(License="MIT")
    assert collector.licence_text(dist) is None
