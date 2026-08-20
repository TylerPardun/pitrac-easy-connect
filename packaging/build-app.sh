#!/usr/bin/env bash
#
# Build the PiTrac app for whichever platform this runs on.
#
#   ./packaging/build-app.sh          native app (.app on macOS, .exe on Windows)
#   ./packaging/build-app.sh --pyz    the portable single file instead
#   ./packaging/build-app.sh --all    both
#
# PyInstaller bundles the interpreter of the machine it runs on, so a Windows
# .exe needs a Windows machine. There is no cross-compiling this: build it on
# the simulator PC, or let the GitHub workflow do it on a Windows runner.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$HERE"
OUT="$HERE/dist"
VERSION="$(python3 -c "import re,pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('src/pitrac_easy_connect/__init__.py').read_text()).group(1))")"
export PITRAC_VERSION="$VERSION"

say()  { printf '  %s\n' "$*"; }
step() { printf '\n\033[1m%s\033[0m\n' "$*"; }

WANT_PYZ=no
WANT_APP=yes
case "${1:-}" in
    --pyz) WANT_PYZ=yes; WANT_APP=no ;;
    --all) WANT_PYZ=yes ;;
    "")    ;;
    *)     printf 'Unknown option: %s\n' "$1" >&2; exit 1 ;;
esac

printf '\nPiTrac %s\n' "$VERSION"
mkdir -p "$OUT"

if [ "$WANT_PYZ" = yes ]; then
    step "Portable single file"
    STAGE="$(mktemp -d)"
    trap 'rm -rf "$STAGE"' EXIT
    cp -r src/pitrac_easy_connect "$STAGE/"
    find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
    cat > "$STAGE/__main__.py" <<'PY'
from pitrac_easy_connect.companion.app import main

raise SystemExit(main())
PY
    PYZ="$OUT/PiTrac-$VERSION.pyz"
    python3 -m zipapp "$STAGE" -o "$PYZ" -p "/usr/bin/env python3"
    chmod +x "$PYZ"
    say "$PYZ ($(du -h "$PYZ" | cut -f1)) — needs Python 3.9+ on the machine"
fi

if [ "$WANT_APP" = yes ]; then
    step "Native app"
    if ! python3 -c "import PyInstaller" 2>/dev/null; then
        say "Installing PyInstaller (build-time only; not shipped)"
        python3 -m pip install --quiet --disable-pip-version-check pyinstaller
    fi

    if [ ! -f packaging/icon/PiTrac.icns ] || [ ! -f packaging/icon/PiTrac.ico ]; then
        say "Generating icons"
        python3 -m pip install --quiet --disable-pip-version-check pillow
        python3 packaging/icon/make-icons.py packaging/icon >/dev/null
        if command -v iconutil >/dev/null; then
            iconutil -c icns packaging/icon/PiTrac.iconset -o packaging/icon/PiTrac.icns
        fi
    fi

    python3 -m PyInstaller --noconfirm --clean \
        --distpath "$OUT" --workpath "$HERE/build" packaging/PiTracCompanion.spec

    case "$(uname -s 2>/dev/null || echo Windows)" in
        Darwin)
            say "$OUT/PiTrac.app ($(du -sh "$OUT/PiTrac.app" | cut -f1))"
            printf '\n  \033[1mUnsigned.\033[0m macOS will refuse to open it after download until it is\n'
            printf '  signed and notarised. Until then: right-click the app and choose Open,\n'
            printf '  or run  xattr -d com.apple.quarantine "%s/PiTrac.app"\n' "$OUT"
            ;;
        MINGW*|MSYS*|CYGWIN*|Windows*)
            say "$OUT/PiTrac.exe"
            printf '\n  \033[1mUnsigned.\033[0m SmartScreen will warn until it is code-signed.\n'
            printf '  Users click More info, then Run anyway.\n'
            ;;
        *)
            say "Built for $(uname -s). Windows and macOS are the supported targets."
            ;;
    esac
fi

printf '\nTo put a build on an enclosure so its owner can download it:\n'
printf '  scp dist/<file> pitracuser@pitrac.local:/tmp/\n'
printf '  ssh pitracuser@pitrac.local "sudo install -D -m 0644 /tmp/<file> \\\n'
printf '      /var/lib/pitrac-easy-connect/companion/<file>"\n\n'
