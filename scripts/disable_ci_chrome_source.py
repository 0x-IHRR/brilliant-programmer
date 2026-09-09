"""Disable only a dedicated Chrome apt source on ephemeral CI runners.

Playwright installs its own Chromium. A mismatched Chrome index must not prevent
installing the unchanged Playwright OS dependencies. Mixed/unknown files fail closed.
"""

import os
import re
from pathlib import Path

URI = "https://dl.google.com/linux/chrome-stable/deb"
ENTRY = re.compile(
    r"deb(?:-src)?\s+(?:\[[^\]\r\n]+\]\s+)?" + re.escape(URI) + r"/?\s+\S+(?:\s+\S+)*"
)


def disable_sources(root: Path) -> list[Path]:
    files = [
        root / "sources.list",
        *sorted((root / "sources.list.d").glob("*.list")),
        *sorted((root / "sources.list.d").glob("*.sources")),
    ]
    selected = []
    for path in files:
        if not path.is_file():
            continue
        lines = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        if not any(URI in line for line in lines):
            continue
        if path.suffix == ".sources":
            fields = {}
            for line in lines:
                key, separator, value = line.partition(":")
                if not separator or key in fields:
                    raise ValueError(f"Cannot safely isolate Chrome source: {path}")
                fields[key] = value.strip()
            safe = (
                fields.get("URIs", "").rstrip("/") == URI
                and set(fields.get("Types", "").split()) <= {"deb", "deb-src"}
                and bool(fields.get("Types"))
            )
        else:
            safe = all(ENTRY.fullmatch(line) for line in lines)
        if not safe or path.with_name(path.name + ".disabled").exists():
            raise ValueError(f"Cannot safely isolate Chrome source: {path}")
        selected.append(path)
    # Validate every matching file before changing any. Never split mixed stanzas
    # or guess a runner filename; preserve each original as an inactive backup.
    for path in selected:
        path.rename(path.with_name(path.name + ".disabled"))
        print(f"Disabled dedicated apt source {path}: {URI}")
    if not selected:
        print(f"No active source file contains {URI}")
    return selected


if __name__ == "__main__":
    if os.environ.get("GITHUB_ACTIONS") != "true":
        raise SystemExit("This operation is restricted to the ephemeral CI runner")
    disable_sources(Path("/etc/apt"))
