#!/usr/bin/env bash
#
# Build the PiTrac Easy-Connect app for whichever platform this runs on.
#
#   ./packaging/build-app.sh          native app for this operating system
#
# PyInstaller bundles the interpreter of the machine it runs on, so a Windows
# .exe needs a Windows machine. There is no cross-compiling this: build it on
# the simulator PC, or let the GitHub workflow do it on a Windows runner.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)' || {
    printf 'Building the desktop app requires Python 3.10 or newer (found %s).\n' \
        "$(python3 -V 2>&1)" >&2
    exit 1
}
OUT="$HERE/dist"
VERSION="$(python3 -c "import re,pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('src/pitrac_easy_connect/__init__.py').read_text()).group(1))")"
export PITRAC_VERSION="$VERSION"

say()  { printf '  %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

case "${1:-}" in
    "")    ;;
    *)     printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
esac

printf '\nPiTrac %s\n' "$VERSION"
mkdir -p "$OUT"
# Only known application outputs are removed. This prevents a stale artifact
# from a different platform or version being packaged as the current build.
rm -rf "$HERE/build/PiTrac-Easy-Connect" \
    "$OUT/PiTrac Easy-Connect" "$OUT/PiTrac Easy-Connect.app" \
    "$OUT/PiTrac Easy-Connect.exe" "$OUT/payload"
rm -f "$OUT"/PiTrac-Easy-Connect-*.zip

step "Native app"
    # Pinned, so two builds of the same commit contain the same code and the
    # licences in NOTICE.md keep matching what actually shipped.
    # Installed every time, not only when missing. Accepting whatever version
    # happened to be present meant a build could use a different PyInstaller
    # than the pins say, and ship different code than the licence list beside
    # it claims. Pillow is in the pinned set too, for the icons below.
    say "Installing the pinned build environment (not shipped; see NOTICE.md)"
    python3 -m pip install --quiet --disable-pip-version-check \
        -r packaging/build-requirements.txt

    say "Collecting third-party licence texts"
    python3 packaging/collect-licences.py

    if [ ! -f packaging/icon/PiTrac.icns ] || [ ! -f packaging/icon/PiTrac.ico ]; then
        say "Generating icons"
        python3 packaging/icon/make-icons.py packaging/icon >/dev/null
        if command -v iconutil >/dev/null; then
            iconutil -c icns packaging/icon/PiTrac.iconset -o packaging/icon/PiTrac.icns
        fi
    fi

    python3 -m PyInstaller --noconfirm --clean \
        --distpath "$OUT" --workpath "$HERE/build" packaging/PiTrac-Easy-Connect.spec

case "$(uname -s 2>/dev/null || echo Windows)" in
        Darwin)
            say "$OUT/PiTrac Easy-Connect.app ($(du -sh "$OUT/PiTrac Easy-Connect.app" | cut -f1))"
            printf '\n  \033[1mUnsigned.\033[0m macOS will refuse to open it after download until it is\n'
            printf '  signed and notarised. Until then: right-click the app and choose Open,\n'
            printf '  or run  xattr -d com.apple.quarantine "%s/PiTrac Easy-Connect.app"\n' "$OUT"
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows*)
            say "$OUT/PiTrac Easy-Connect.exe"
            printf '\n  \033[1mUnsigned.\033[0m SmartScreen will warn until it is code-signed.\n'
            printf '  Users click More info, then Run anyway.\n'
            ;;
        *)
            say "$OUT/PiTrac Easy-Connect ($(du -h "$OUT/PiTrac Easy-Connect" | cut -f1))"
            printf '\n  Requires WebKitGTK 4.1 at runtime (for example libwebkit2gtk-4.1-0 on Ubuntu).\n'
            ;;
esac

printf '\nTo put a build on an enclosure so its owner can download it:\n'
printf '  scp dist/<file> pitracuser@pitrac.local:/tmp/\n'
printf '  ssh pitracuser@pitrac.local "sudo install -D -m 0644 /tmp/<file> \\\n'
printf '      /var/lib/pitrac-easy-connect/companion/<file>"\n\n'
