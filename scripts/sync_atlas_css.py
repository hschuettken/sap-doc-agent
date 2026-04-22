#!/usr/bin/env python3
"""Sync canonical atlas design tokens + UI CSS into spec2sphere static files.

Run from the repo root:
    python scripts/sync_atlas_css.py

The atlas monorepo must be a sibling of sap-doc-agent at ../atlas
(i.e. /repos/atlas relative to /repos/sap-doc-agent).
"""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_ROOT = REPO_ROOT.parent / "atlas"
STATIC_DIR = REPO_ROOT / "src" / "spec2sphere" / "web" / "static"

SOURCES = {
    "atlas-tokens.css": ATLAS_ROOT / "packages" / "atlas-design-tokens" / "dist" / "tokens.css",
}


def sync() -> None:
    missing = [src for src in SOURCES.values() if not src.exists()]
    if missing:
        print("ERROR: canonical source files not found:")
        for p in missing:
            print(f"  {p}")
        sys.exit(1)

    STATIC_DIR.mkdir(parents=True, exist_ok=True)

    for dest_name, src_path in SOURCES.items():
        dest = STATIC_DIR / dest_name
        shutil.copy2(src_path, dest)
        print(f"  ✓ {src_path.relative_to(ATLAS_ROOT)}  →  {dest.relative_to(REPO_ROOT)}")

    print("\nDone. spec2sphere static CSS is in sync with @atlas/design-tokens.")


if __name__ == "__main__":
    sync()
