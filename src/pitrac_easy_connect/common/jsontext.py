"""Parsing JSON that arrived over a network.

Python's JSON parser recurses once per level of nesting, so a payload nested
about ten thousand deep raises ``RecursionError``. That is not a ``ValueError``,
and every boundary in this project guarded itself by catching ``ValueError`` --
so a body that could not be parsed stopped being a refusal and became an
unhandled exception. On the enclosure's HTTP portal it escaped the request
entirely: the caller got a dropped connection and the log got a traceback,
from any device on the residence network, with no credentials at all.

Depth is capped rather than caught. The interfaces here are configuration and
shot data, none of it nested more than a few levels, so anything deeper is not
a payload that got large -- it is someone seeing what happens. The
``RecursionError`` catch below is a backstop for a parser whose own limit is
lower than the cap.
"""

import json
from typing import Any

#: Far more nesting than any message this project defines, and far less than
#: the parser's own limit. A backup's settings tree is the deepest thing here
#: at well under ten.
MAX_DEPTH = 64


def loads(text: str, max_depth: int = MAX_DEPTH) -> Any:
    """``json.loads``, but a refusal rather than an exception for deep input.

    Raises ``ValueError`` for anything malformed, which is what every caller
    already handles.
    """

    _refuse_if_too_deep(text, max_depth)
    try:
        return json.loads(text)
    except RecursionError as exc:      # pragma: no cover - depth is capped above
        raise ValueError("that is nested too deeply to read") from exc


def _refuse_if_too_deep(text: str, max_depth: int) -> None:
    """Count nesting without parsing, ignoring brackets inside strings.

    Cheaper than parsing and, unlike parsing, it cannot itself run out of
    stack. A string's contents are skipped so that a quoted bracket is not
    mistaken for structure, and a backslash escape is skipped with it.
    """

    depth = 0
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character in "[{":
            depth += 1
            if depth > max_depth:
                raise ValueError("that is nested too deeply to read")
        elif character in "]}":
            depth -= 1
