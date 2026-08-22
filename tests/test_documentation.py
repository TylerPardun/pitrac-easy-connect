"""Keep the guides honest.

A guide that quotes a timeout or an error code the software no longer uses is
worse than no guide, because the reader trusts it. These tests fail when the
documentation and the code drift apart.
"""

import re
from pathlib import Path

import pytest

from pitrac_easy_connect import __version__
from pitrac_easy_connect.common.errors import catalogue
from pitrac_easy_connect.common.identity import HOTSPOT_SETUP_URL
from pitrac_easy_connect.pi.pairing import PAIRING_WINDOW_SECONDS
from pitrac_easy_connect.pi.relay import DEFAULT_RELAY_PORTS
from pitrac_easy_connect.pi.wifi import CONFIRMATION_SECONDS
from pitrac_easy_connect.models import Simulator

DOCS = Path(__file__).resolve().parent.parent / "docs"
README = Path(__file__).resolve().parent.parent / "README.md"

GUIDES = [DOCS / "beginner-guide.md", DOCS / "beginner-guide.html"]
ALL_DOCS = GUIDES + [DOCS / "operator-guide.md", DOCS / "architecture.md", README]


def read(path):
    """Read a document, or skip if this checkout does not have it.

    The guides are kept locally for reference but are not published, so they
    are absent on a CI runner and on anyone else's clone. These checks are
    worth keeping — they catch a guide quoting a timing or an error code the
    code no longer has — but only where there is something to check.
    """

    if not path.exists():
        pytest.skip("{} is not published; it is kept locally only".format(path.name))
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("path", ALL_DOCS, ids=lambda p: p.name)
def test_every_error_code_quoted_in_the_docs_exists(path):
    known = set(catalogue())
    quoted = set(re.findall(r"PT-[A-Z]+-\d{3}", read(path)))
    assert quoted <= known, "documented codes that no longer exist: {}".format(quoted - known)


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_the_guides_print_the_address_the_hotspot_really_uses(path):
    assert HOTSPOT_SETUP_URL in read(path)


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_the_guides_describe_the_real_pairing_window(path):
    assert PAIRING_WINDOW_SECONDS == 300.0
    assert "five minutes" in read(path)


@pytest.mark.parametrize("path", ALL_DOCS, ids=lambda p: p.name)
def test_no_document_still_tells_anyone_to_enter_a_code(path):
    """The code is gone from the product.

    Explaining why it was removed is fine and worth keeping; what must not
    survive is any instruction to find one, type one, or wait for a fresh one,
    because there is nothing for a reader to do about it.
    """

    text = " ".join(read(path).lower().split())
    for phrase in (
        "type the six",
        "type the code",
        "enter the code",
        "enter this code",
        "read the code",
        "new code",
        "codes last",
        "code has expired",
        "asks for a six-digit",
    ):
        assert phrase not in text, "{} still tells the reader to use a code".format(path.name)


@pytest.mark.parametrize("path", GUIDES, ids=lambda p: p.name)
def test_the_guides_describe_the_real_rollback_window(path):
    assert CONFIRMATION_SECONDS == 150.0
    assert "two and a half minutes" in read(path)


def test_the_operator_guide_names_the_real_relay_ports():
    text = read(DOCS / "operator-guide.md")
    for simulator, port in DEFAULT_RELAY_PORTS.items():
        assert str(port) in text, "{} port {} is not documented".format(simulator.value, port)


def test_the_operator_guide_names_the_real_config_keys():
    from pitrac_easy_connect.pi.pitrac import SIMULATOR_KEYS

    text = read(DOCS / "operator-guide.md")
    for address_key, port_key in SIMULATOR_KEYS.values():
        assert address_key.rsplit(".", 1)[-1] in text
        assert port_key.rsplit(".", 1)[-1] in text


def test_nothing_public_quotes_a_version_that_is_not_the_current_one():
    """The README deliberately names no version -- it is written for someone
    choosing whether to use this, not tracking releases. What matters is that
    anywhere a version *is* printed, it is this one.
    """

    import re as _re

    root = Path(__file__).resolve().parent.parent
    stale = []
    for path in (README, root / "site" / "index.html", root / "NOTICE.md"):
        if not path.exists():
            continue
        text = read(path)
        # Only versions attached to *our* name. A licence list full of other
        # projects' versions is not this test's business.
        ours = _re.findall(r"(?:PiTrac[- ]Easy[- ]Connect[- ])(\d+\.\d+\.\d+)", text)
        ours += _re.findall(r"\*\*Version:\*\*\s*(\d+\.\d+\.\d+)", text)
        for quoted in set(ours):
            if quoted != __version__:
                stale.append("{}: {}".format(path.name, quoted))
    assert not stale, "these name a version that is not {}: {}".format(__version__, stale)


def test_the_illustrated_guide_is_self_contained():
    """A strict content policy blocks anything but the one permitted font host."""

    text = read(DOCS / "beginner-guide.html")
    # Only things the page actually fetches count. Addresses printed as text for
    # the reader to type are not resource references.
    references = re.findall(r'(?:href|src)\s*=\s*"([^"]+)"', text)
    references += re.findall(r'url\(\s*[\'"]?([^)\'"]+)', text)
    allowed = ("https://fonts.googleapis.com", "https://fonts.gstatic.com")
    external = [
        reference
        for reference in references
        if "//" in reference and not reference.startswith(allowed)
    ]
    assert not external, "the guide would fail to load: {}".format(external)
    assert "<img" not in text, "images must be inline SVG, not external files"


def test_the_illustrated_guide_defines_both_themes():
    text = read(DOCS / "beginner-guide.html")
    assert ':root:not([data-theme="light"])' in text, "system dark mode is unhandled"
    assert ':root[data-theme="dark"]' in text, "an explicit dark choice is unhandled"
    assert "background:var(--paper)" in text, "the body must paint its own ground"


def test_every_documented_error_code_can_actually_happen():
    """A guide that describes an error the software never produces is a lie.

    Every catalogue entry must be reachable: referenced by name somewhere in the
    code, or produced by its literal code string.
    """

    import re

    source_root = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    catalogue_file = source_root / "common" / "errors.py"
    catalogue_text = read(catalogue_file)
    elsewhere = "\n".join(
        read(path)
        for path in source_root.rglob("*.py")
        if "__pycache__" not in str(path) and path != catalogue_file
    )

    names = dict(re.findall(r'(\w+) = _define\(\s*\n\s*"([A-Z0-9\-]+)"', catalogue_text))
    unreachable = [
        code
        for name, code in names.items()
        if not re.search(r"\b%s\b" % re.escape(name), elsewhere) and code not in elsewhere
    ]
    assert not unreachable, "documented but never produced: {}".format(sorted(unreachable))


# --- The packaged build -----------------------------------------------------


def test_the_build_spec_names_every_module_the_app_loads_at_runtime():
    """PyInstaller cannot see imports made through runtime lookups.

    A module missing from hiddenimports builds fine and then fails on the user's
    machine, which is the worst time to find out.
    """

    import re

    spec = read(Path(__file__).resolve().parent.parent / "packaging" / "PiTrac-Easy-Connect.spec")
    hidden = set(re.findall(r'"(pitrac_easy_connect\.[A-Za-z_.]+)"', spec))

    source_root = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    companion = source_root / "companion"
    needed = {
        "pitrac_easy_connect.companion." + path.stem
        for path in companion.glob("*.py")
        if path.stem not in ("__init__", "app")
    }
    missing = needed - hidden
    assert not missing, "the packaged app would fail to import: {}".format(sorted(missing))


def test_the_packaged_entry_point_opens_a_window():
    """Double-clicking a packaged build must not open a browser tab."""

    entry = read(Path(__file__).resolve().parent.parent / "packaging" / "app_entry.py")
    assert "frozen" in entry
    assert '"--window"' in entry


def test_the_release_notes_warn_about_the_unsigned_builds():
    workflow = read(
        Path(__file__).resolve().parent.parent / ".github" / "workflows" / "build.yml"
    )
    assert "Run anyway" in workflow, "Windows users need to be told about SmartScreen"
    assert "right-click" in workflow.lower(), "macOS users need to be told about Gatekeeper"


def test_the_app_calls_itself_one_thing():
    """It is named separately from PiTrac, so the name has to be used as given.

    The window title said "PiTrac Easy-Connect" while buttons inside it said
    "Easy Connect", which reads as two different products.
    """

    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    offenders = []
    for path in sorted(source.rglob("*.py")):
        if path.name == "protocols.py":
            continue  # its DeviceID goes on the wire; that string is not a label
        tree = ast.parse(path.read_text())

        # Docstrings are prose about the code, not text anyone reads on screen.
        # Everything else that is a string is fair game — including the pages,
        # which are one enormous string literal each.
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                first = node.body[0] if node.body else None
                if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant):
                    if isinstance(first.value.value, str):
                        docstrings.add(id(first.value))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            if id(node) in docstrings or "Easy Connect" not in node.value:
                continue
            line = node.value[node.value.index("Easy Connect") - 30:][:70]
            offenders.append("{}:{} …{}…".format(path.name, node.lineno, line.strip()))

    assert not offenders, "these say 'Easy Connect' rather than 'Easy-Connect': {}".format(
        offenders
    )


def test_the_error_reference_is_current():
    """Generated from the catalogue, so it cannot drift.

    A code added, renumbered, or reworded in ``common/errors.py`` fails this
    until the reference has been regenerated:

        python3 packaging/make-error-reference.py
    """

    guide = DOCS / "operator-guide.md"
    if not guide.exists():
        pytest.skip("the operator guide is not published; it is kept locally only")

    import subprocess
    import sys

    root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, str(root / "packaging" / "make-error-reference.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_every_error_code_is_in_the_reference():
    """A code nobody documented is one nobody can look up when it appears."""

    guide = DOCS / "operator-guide.md"
    if not guide.exists():
        pytest.skip("the operator guide is not published; it is kept locally only")

    text = read(guide)
    missing = [code for code in sorted(catalogue()) if "`{}`".format(code) not in text]
    assert not missing, "not in the operator guide: {}".format(missing)


def test_the_two_beginner_guides_cover_the_same_steps():
    """The printable HTML is maintained by hand alongside the markdown.

    Two copies of the same instructions drift, and the one that drifts is
    whichever the author did not have open. This catches a step added to one
    and forgotten in the other.
    """

    import html as html_module
    import re

    md_path, html_path = DOCS / "beginner-guide.md", DOCS / "beginner-guide.html"
    if not md_path.exists() or not html_path.exists():
        pytest.skip("the guides are not published; they are kept locally only")

    def normalise(title):
        title = re.sub(r"^Step\s+\S+\s*[-\u2014]\s*", "", title.strip())
        return re.sub(r"[^a-z ]", "", title.lower()).strip()

    in_md = {normalise(m) for m in re.findall(r"^## (.+)$", read(md_path), re.M)}
    in_html = {
        normalise(html_module.unescape(re.sub("<[^>]+>", "", m)))
        for m in re.findall(r"<h2[^>]*>(.*?)</h2>", read(html_path), re.S)
    }

    # Wording differs a little between the two; only whole missing steps matter.
    # The reverse check used to rebind its own loop variable, so it compared
    # each title against itself, always found a match, and was never asserted
    # anyway -- a step could be added to the printable guide alone and nothing
    # would say so.
    only_md = {m for m in in_md if not any(m[:14] in h for h in in_html)}
    only_html = {h for h in in_html if not any(h[:14] in m for m in in_md)}
    assert not only_md, "in the markdown guide but not the printable one: {}".format(only_md)
    assert not only_html, "in the printable guide but not the markdown one: {}".format(only_html)


def test_no_error_code_is_hardcoded_outside_the_catalogue():
    """Two sources of truth for a code is one too many.

    A literal like ``"PT-SIM-004"`` sitting in a module silently survives the
    code being renumbered or removed in ``common/errors.py``, and then reports
    something that no longer exists.
    """

    import re

    root = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"
    offenders = []
    for path in sorted(root.rglob("*.py")):
        if path.name == "errors.py":
            continue
        for number, line in enumerate(path.read_text().splitlines(), 1):
            if re.search(r'["\']PT-[A-Z]+-\d{3}["\']', line):
                offenders.append("{}:{}".format(path.name, number))
    assert not offenders, "use the named constant instead: {}".format(offenders)
