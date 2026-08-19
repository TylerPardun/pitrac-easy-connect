"""Every route a page calls must exist, with the method the page uses.

This exists because the Companion's Search button was broken for a while: the
page sent GET and the server only answered POST. Every test called the API with
an explicit method, so nothing noticed. These tests read the routes straight out
of the page's own JavaScript.
"""

import re
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parent.parent / "src" / "pitrac_easy_connect"


def calls_in(page_source: str):
    """Find every api(...) call and work out the method the helper will use.

    The helper in both pages is ``api(path, body)`` and sends POST when a body
    is present, GET otherwise.
    """

    calls = set()
    for match in re.finditer(r'api\(\s*"([^"]+)"\s*(,)?', page_source):
        path, has_body = match.group(1), bool(match.group(2))
        calls.add((path, "POST" if has_body else "GET"))
    return calls


def routes_in(server_source: str):
    """Find the routes the server registers, split by method."""

    get_block = server_source.split("def do_POST")[0]
    post_block = server_source.split("def do_POST")[1] if "def do_POST" in server_source else ""
    return (
        {(path, "GET") for path in re.findall(r'path == "(/api/[^"]+)"', get_block)}
        | {(path, "GET") for path in re.findall(r'path in \("(/api/[^"]+)"', get_block)}
        | {(path, "POST") for path in re.findall(r'"(/api/[^"]+)":', post_block)}
    )


CASES = [
    ("companion", "companion/page.py", "companion/web.py"),
    ("portal", "pi/portal_page.py", "pi/portal.py"),
]


@pytest.mark.parametrize("name,page,server", CASES, ids=[case[0] for case in CASES])
def test_every_route_the_page_calls_is_served(name, page, server):
    called = calls_in((SOURCE / page).read_text())
    served = routes_in((SOURCE / server).read_text())

    missing = called - served
    assert not missing, "{} page calls routes the server does not answer: {}".format(
        name, sorted(missing)
    )


@pytest.mark.parametrize("name,page,server", CASES, ids=[case[0] for case in CASES])
def test_no_route_is_called_with_the_wrong_method(name, page, server):
    called = calls_in((SOURCE / page).read_text())
    served = routes_in((SOURCE / server).read_text())
    served_paths = {path for path, _method in served}

    wrong = [
        (path, method)
        for path, method in called
        if path in served_paths and (path, method) not in served
    ]
    assert not wrong, "{} page uses the wrong method for: {}".format(name, wrong)
