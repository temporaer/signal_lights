#!/usr/bin/env python3
"""Bump version in manifest.json and pyproject.toml."""

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST = REPO_ROOT / "custom_components" / "signal_lights" / "manifest.json"
PYPROJECT = REPO_ROOT / "pyproject.toml"

SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")


def parse_version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def get_current_version() -> str:
    manifest = json.loads(MANIFEST.read_text())
    return manifest["version"]


def bump(new_version: str) -> None:
    if not SEMVER_RE.match(new_version):
        print(f"Error: '{new_version}' is not valid semver (expected X.Y.Z)", file=sys.stderr)
        sys.exit(1)

    current = get_current_version()
    if new_version == current:
        print(f"Error: version is already {current}", file=sys.stderr)
        sys.exit(1)

    if parse_version_tuple(new_version) <= parse_version_tuple(current):
        print(f"Error: new version {new_version} is not greater than current {current}", file=sys.stderr)
        sys.exit(1)

    # Update manifest.json
    manifest = json.loads(MANIFEST.read_text())
    manifest["version"] = new_version
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")

    # Update pyproject.toml
    pyproject_text = PYPROJECT.read_text()
    pyproject_text = re.sub(
        r'^version\s*=\s*"[^"]+"',
        f'version = "{new_version}"',
        pyproject_text,
        count=1,
        flags=re.MULTILINE,
    )
    PYPROJECT.write_text(pyproject_text)

    print(f"Bumped version: {current} → {new_version}")
    print(f"  Updated: {MANIFEST.relative_to(REPO_ROOT)}")
    print(f"  Updated: {PYPROJECT.relative_to(REPO_ROOT)}")
    print("\nNext steps:")
    print(f"  git commit -am 'Bump version to {new_version}'")
    print(f"  git tag v{new_version}")
    print(f"  git push origin main v{new_version}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <new-version>", file=sys.stderr)
        print(f"  Current version: {get_current_version()}", file=sys.stderr)
        sys.exit(1)
    bump(sys.argv[1])
