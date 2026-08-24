"""Inspect the exact desktop archive with the same validator used at runtime."""

import argparse
import pathlib
import shutil
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from pitrac_easy_connect.companion import self_update  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("archive", type=pathlib.Path)
    parser.add_argument("--system", choices=("Darwin", "Windows", "Linux"), required=True)
    parser.add_argument("--arch", choices=("arm64", "x86_64"), required=True)
    parser.add_argument("--version", required=True)
    args = parser.parse_args(argv)
    temporary = pathlib.Path(tempfile.mkdtemp(prefix="pitrac-archive-check-"))
    try:
        extracted = self_update.extract_safely(args.archive, temporary / "extracted",
                                               system=args.system)
        app = self_update.validate_structure(extracted, args.version, system=args.system,
                                             machine=args.arch)
        helper = self_update.helper_path(app.install_root, system=args.system)
        if not helper.is_file():
            raise self_update.SelfUpdateError("the updater helper is missing")
        # validate_structure executes the exact extracted app through the
        # cross-platform version-probe file contract. This catches broken
        # symlinks, missing runtimes, and lost executable bits.
        print("validated {} {} {} at {}".format(args.system, args.arch, args.version,
                                                app.install_root))
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
