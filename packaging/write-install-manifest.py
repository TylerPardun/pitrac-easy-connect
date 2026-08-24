"""Write the package sentinel used by the desktop updater."""

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pitrac_easy_connect.companion.self_update import package_manifest  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=pathlib.Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--system", choices=("Darwin", "Windows", "Linux"), required=True)
    parser.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    args = parser.parse_args(argv)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    value = package_manifest(args.version, system=args.system, machine=args.arch)
    args.output.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
