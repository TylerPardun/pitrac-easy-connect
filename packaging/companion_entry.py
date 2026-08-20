"""Entry point for the packaged PiTrac app.

A packaged build is launched by double-clicking, with no arguments, so it opens
its own window rather than a browser tab. Anyone running it from a terminal with
arguments gets exactly what they asked for instead.
"""

import sys

from pitrac_easy_connect.companion.app import main

if __name__ == "__main__":
    arguments = sys.argv[1:]
    if getattr(sys, "frozen", False) and not arguments:
        arguments = ["--window"]
    raise SystemExit(main(arguments))
