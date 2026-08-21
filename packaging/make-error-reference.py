#!/usr/bin/env python3
"""Regenerate the error reference in the operator guide from the catalogue.

The point is that nobody maintains it by hand. A code added, renumbered, or
reworded in ``common/errors.py`` shows up here the next time this runs, and
``tests/test_documentation.py`` fails until it has.

    python3 packaging/make-error-reference.py          # rewrite the section
    python3 packaging/make-error-reference.py --check  # exit 1 if it is stale
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pitrac_easy_connect.common.errors import catalogue  # noqa: E402

GUIDE = ROOT / "docs" / "operator-guide.md"
START = "<!-- error-reference:start -->"
END = "<!-- error-reference:end -->"

FAMILIES = [
    ("PT-NET", "Network and Wi-Fi"),
    ("PT-PAIR", "Pairing and ownership"),
    ("PT-LINK", "The link to the computer"),
    ("PT-PI", "The enclosure itself"),
    ("PT-SIM", "The golf simulator"),
    ("PT-CFG", "Settings and backups"),
]


def render() -> str:
    known = catalogue()
    lines = [
        START,
        "",
        "Every code the software can produce, generated from the catalogue by",
        "`packaging/make-error-reference.py`. Do not edit this section by hand.",
        "",
    ]
    for prefix, title in FAMILIES:
        codes = sorted(code for code in known if code.startswith(prefix + "-"))
        if not codes:
            continue
        lines += ["### {}".format(title), "", "| Code | What failed | What to do |", "|---|---|---|"]
        for code in codes:
            info = known[code]
            lines.append(
                "| `{}` | {} | {} |".format(
                    code,
                    info.failed.rstrip("."),
                    info.next_step.rstrip("."),
                )
            )
        lines.append("")
    lines.append(END)
    return "\n".join(lines)


def main() -> int:
    text = GUIDE.read_text()
    block = render()
    if START in text and END in text:
        updated = re.sub(
            re.escape(START) + r".*?" + re.escape(END), lambda _m: block, text, flags=re.S
        )
    else:
        updated = text.rstrip() + "\n\n## Every error code\n\n" + block + "\n"

    if "--check" in sys.argv:
        if updated != text:
            print("The error reference in the operator guide is out of date.")
            print("Run: python3 packaging/make-error-reference.py")
            return 1
        print("Error reference is current.")
        return 0

    GUIDE.write_text(updated)
    print("Wrote {} codes to {}".format(len(catalogue()), GUIDE.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
