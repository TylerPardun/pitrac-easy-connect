#!/usr/bin/env python3
"""Write a CycloneDX SBOM for one packaged build, from what it actually
contains -- not from a dependency list someone might forget to update.

Reuses bundled-licences.py's own PyInstaller Analysis-00.toc reader (the
same one that gates NOTICE.md completeness in CI) as the single source of
truth for what shipped, and collect-licences.py's installed-distribution
lookup for version numbers. An SBOM built from a different enumeration than
the one NOTICE.md is checked against could drift from both without either
check ever catching it; this cannot, because it is the same enumeration.

    python3 packaging/write-sbom.py --out sbom.json --toc build/.../Analysis-00.toc \
        --component-name "PiTrac Easy-Connect" --component-version 0.9.0 \
        --platform macos-apple-silicon
"""

import argparse
import importlib.util
import json
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name):
    path = ROOT / "packaging" / "{}.py".format(name.replace("_", "-"))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


bundled_licences = _load("bundled_licences")
collect_licences = _load("collect_licences")


def _version_for(name: str) -> str:
    """Best-effort version lookup: the credited name is not always the exact
    distribution name (Microsoft C runtime, WebView2, CPython itself are not
    Python distributions at all), so a miss is reported as unknown rather
    than guessed at."""

    distributions = collect_licences.installed_distributions()
    key = name.lower().replace("_", "-")
    dist = distributions.get(key)
    if dist is not None:
        return str(dist.metadata["Version"])
    return ""


def build_sbom(*, toc: Path, component_name: str, component_version: str,
               platform: str) -> dict:
    found = bundled_licences.bundled(toc)
    notice = bundled_licences.credited()
    missing = sorted(name for name in found if name.lower() not in notice)
    if missing:
        raise SystemExit(
            "refusing to write an SBOM that disagrees with NOTICE.md: "
            "not credited there: {}".format(", ".join(missing))
        )

    components = []
    for name, count in sorted(found.items()):
        components.append({
            "type": "library",
            "bom-ref": "component-{}".format(name.lower().replace(" ", "-")),
            "name": name,
            "version": _version_for(name) or "unknown",
            "properties": [
                {"name": "pitrac:bundledFileCount", "value": str(count)},
            ],
        })

    return {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": "urn:uuid:{}".format(uuid.uuid4()),
        "version": 1,
        "metadata": {
            "component": {
                "type": "application",
                "name": component_name,
                "version": component_version,
                "properties": [
                    {"name": "pitrac:platform", "value": platform},
                ],
            },
        },
        "components": components,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--toc", type=Path, required=True)
    parser.add_argument("--component-name", required=True)
    parser.add_argument("--component-version", required=True)
    parser.add_argument("--platform", required=True)
    arguments = parser.parse_args(argv)

    if not arguments.toc.exists():
        raise SystemExit("no build manifest at {}; build first".format(arguments.toc))

    sbom = build_sbom(
        toc=arguments.toc, component_name=arguments.component_name,
        component_version=arguments.component_version, platform=arguments.platform,
    )
    arguments.out.parent.mkdir(parents=True, exist_ok=True)
    arguments.out.write_text(json.dumps(sbom, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("Wrote {} listing {} components for {}".format(
        arguments.out, len(sbom["components"]), arguments.platform
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
