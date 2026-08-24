"""Entry point for the independently packaged desktop update helper."""

import sys

from pitrac_easy_connect.companion.self_update import run_helper_cli


if __name__ == "__main__":
    raise SystemExit(run_helper_cli(sys.argv[1:]))
