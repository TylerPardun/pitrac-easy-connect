#!/bin/zsh
# Double-click to open PiTrac as an app window.
set -e
cd "${0:A}:h" 2>/dev/null || cd "$(dirname "$0")"
PYTHONPATH=src exec /usr/bin/python3 -m pitrac_easy_connect.companion.app --window
