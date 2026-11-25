#!/usr/bin/env bash
#
# Run every check this machine can, without using any CI minutes.
#
#   ./packaging/check.sh                  the suite, and PiTrac's real web server
#   ./packaging/check.sh --pitrac main    against PiTrac as it is today, which is
#                                         how to find out what it has changed
#   ./packaging/check.sh --quick          the suite alone
#
# Works on macOS, Linux, and Windows under Git Bash. Everything it downloads
# goes under .check/, which git ignores and which is safe to delete.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
CACHE="$HERE/.check"
REVISION=tested
QUICK=no
while [ $# -gt 0 ]; do
    case "$1" in
        --quick)  QUICK=yes ;;
        --pitrac) shift; REVISION="${1:?--pitrac needs a branch or commit}" ;;
        *) printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
    esac
    shift
done

# The release-signing tests need an OpenSSL with Ed25519. Apple's own python3
# does not have one and fails them, so look for a newer interpreter first.
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
    for candidate in python3.13 python3.14 python3.12 python3 python; do
        if command -v "$candidate" >/dev/null \
            && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3, 10))' 2>/dev/null; then
            PYTHON="$candidate"; break
        fi
    done
fi
[ -n "$PYTHON" ] || { echo "Python 3.10 or newer is needed." >&2; exit 1; }

# Prints the path of a virtual environment's own interpreter.
venv() {
    [ -d "$1" ] || "$PYTHON" -m venv "$1"
    if [ -x "$1/bin/python" ]; then echo "$1/bin/python"; else echo "$1/Scripts/python.exe"; fi
}

OURS="$(venv "$CACHE/venv")"
# Editable, so a subprocess a test starts finds this source too.
"$OURS" -m pip install --quiet --disable-pip-version-check -e ".[test]"
export PATH="$(dirname "$OURS"):$PATH"

if [ "$QUICK" = no ]; then
    [ "$REVISION" != tested ] || REVISION="$("$OURS" -c \
        'from pitrac_easy_connect.pi.pitrac_api import TESTED_COMMIT; print(TESTED_COMMIT)')"
    if [ ! -d "$CACHE/PiTrac" ]; then
        git clone --quiet --filter=blob:none --no-checkout \
            https://github.com/PiTracLM/PiTrac "$CACHE/PiTrac"
        git -C "$CACHE/PiTrac" sparse-checkout set Software/web-server
    fi
    git -C "$CACHE/PiTrac" fetch --quiet origin
    git -C "$CACHE/PiTrac" checkout --quiet --detach "origin/$REVISION" 2>/dev/null \
        || git -C "$CACHE/PiTrac" checkout --quiet --detach "$REVISION"
    THEIRS="$(venv "$CACHE/pitrac-venv")"
    # spidev drives the strobe board and only builds on a Pi.
    WEB="$CACHE/PiTrac/Software/web-server"
    { grep -v '^spidev' "$WEB/requirements.txt"; grep '^opencv' "$WEB/requirements-test.txt"; } \
        > "$CACHE/pitrac-requirements.txt"
    "$THEIRS" -m pip install --quiet --disable-pip-version-check -r "$CACHE/pitrac-requirements.txt"
    export PITRAC_SOURCE="$CACHE/PiTrac" PITRAC_PYTHON="$THEIRS"
    printf 'PiTrac %s\n' "$(git -C "$CACHE/PiTrac" log -1 --format='%h %cs %s')"
fi

"$OURS" -m pytest -q
"$OURS" packaging/check-native-only.py
