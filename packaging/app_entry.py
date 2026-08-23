"""Entry point for the packaged native PiTrac desktop app."""

import sys

from pitrac_easy_connect.companion.app import main

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
