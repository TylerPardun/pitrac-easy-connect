#!/usr/bin/env bash
#
# Build the Companion into a single file that can be handed to a simulator PC.
#
#   ./packaging/build-companion.sh            build the .pyz (works anywhere)
#   ./packaging/build-companion.sh --exe      also build a Windows .exe (Windows only)
#
# The .pyz is one file with no installation and no dependencies, but it needs
# Python already on the PC. The .exe needs neither, but can only be built on
# Windows, because PyInstaller bundles that platform's interpreter.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HERE/dist"
VERSION="$(python3 -c "import re,pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('$HERE/src/pitrac_easy_connect/__init__.py').read_text()).group(1))")"

say() { printf '  %s\n' "$*"; }
printf '\nBuilding PiTrac Easy Connect Companion %s\n\n' "$VERSION"

mkdir -p "$OUT"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

cp -r "$HERE/src/pitrac_easy_connect" "$STAGE/"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
cat > "$STAGE/__main__.py" <<'PY'
from pitrac_easy_connect.companion.app import main

raise SystemExit(main())
PY

PYZ="$OUT/PiTracCompanion-$VERSION.pyz"
python3 -m zipapp "$STAGE" -o "$PYZ" -p "/usr/bin/env python3"
chmod +x "$PYZ"
say "Built $PYZ ($(du -h "$PYZ" | cut -f1))"

if [ "${1:-}" = "--exe" ]; then
    case "$(uname -s 2>/dev/null || echo Windows)" in
        MINGW*|MSYS*|CYGWIN*|Windows*) ;;
        *) printf '\nA Windows .exe can only be built on Windows.\n'
           printf 'Run this on the simulator PC, or in a Windows CI job.\n\n'
           exit 1 ;;
    esac
    python -m pip install --quiet pyinstaller
    python -m PyInstaller --distpath "$OUT" --workpath "$STAGE/build" \
        --specpath "$STAGE" "$HERE/packaging/PiTracCompanion.spec"
    say "Built $OUT/PiTracCompanion.exe"
fi

printf '\nTo put a build on an enclosure so its owner can download it:\n'
printf '  scp %s pitracuser@pitrac.local:/tmp/\n' "$(basename "$PYZ")"
printf '  ssh pitracuser@pitrac.local "sudo install -D -m 0644 \\\n'
printf '      /tmp/%s /var/lib/pitrac-easy-connect/companion/PiTracCompanion.pyz"\n\n' "$(basename "$PYZ")"
