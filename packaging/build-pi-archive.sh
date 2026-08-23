#!/usr/bin/env bash
# Build the dependency-free archive used only to update the Raspberry Pi
# service. This is not a desktop application and is never offered as Linux's
# desktop download.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
VERSION="$(python3 -c "import re,pathlib; print(re.search(r'__version__ = \"([^\"]+)\"', pathlib.Path('src/pitrac_easy_connect/__init__.py').read_text()).group(1))")"
OUTPUT="$ROOT/dist/PiTrac-Easy-Connect-$VERSION.pyz"
STAGE="$(mktemp -d)"
trap 'find "$STAGE" -depth -delete 2>/dev/null || true' EXIT

mkdir -p "$ROOT/dist"
find "$ROOT/dist" -maxdepth 1 -type f -name 'PiTrac-Easy-Connect-*.pyz' -delete
cp -R src/pitrac_easy_connect "$STAGE/"
find "$STAGE" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$STAGE" -name '._*' -type f -delete 2>/dev/null || true

# Development-only helpers do not belong on a customer's enclosure.
for tool in ballmachine.py mock_simulators.py pi/simulated.py; do
    rm -f "$STAGE/pitrac_easy_connect/$tool"
done

cp LICENSE NOTICE.md "$STAGE/"
cat > "$STAGE/__main__.py" <<'PY'
from pitrac_easy_connect.pi.app import main

raise SystemExit(main())
PY

python3 -m zipapp "$STAGE" -o "$OUTPUT" -p "/usr/bin/env python3"
chmod +x "$OUTPUT"
python3 "$OUTPUT" --version >/dev/null
printf '%s\n' "$OUTPUT"
