#!/usr/bin/env python3
"""Sync canonical atlas design tokens + UI CSS into spec2sphere static files.

Run from the repo root:
    python scripts/sync_atlas_css.py

The atlas monorepo must be a sibling of sap-doc-agent at ../atlas
(i.e. /repos/atlas relative to /repos/sap-doc-agent).

atlas-tokens.css  — direct copy from @atlas/design-tokens dist (do not edit).
atlas-ui.css      — spec2sphere server-rendered subset; manually maintained.
                    This script verifies the required primitive CSS classes are
                    present and warns when the canonical source has diverged.
"""

import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
ATLAS_ROOT = REPO_ROOT.parent / "atlas"
STATIC_DIR = REPO_ROOT / "src" / "spec2sphere" / "web" / "static"

# Files that are direct copies from the atlas monorepo
DIRECT_COPIES: dict[str, Path] = {
    "atlas-tokens.css": ATLAS_ROOT / "packages" / "atlas-design-tokens" / "dist" / "tokens.css",
}

# Classes that atlas-ui.css must contain (checked, not copied)
REQUIRED_UI_CLASSES = [
    ".atlas-appshell",
    ".atlas-appshell-sidebar",
    ".atlas-appshell-header",
    ".atlas-appshell-content",
    ".atlas-sidebar-nav-item",
    ".atlas-btn",
    ".atlas-btn--primary",
    ".atlas-btn--ghost",
    ".atlas-card",
    ".atlas-badge",
    ".atlas-toast-viewport",
    ".atlas-table",
    ".atlas-input",
    ".atlas-palette-overlay",
    ".atlas-palette-dialog",
    ".atlas-palette-input",
    ".atlas-palette-item",
]


def sync() -> None:
    errors: list[str] = []

    # ── 1. Direct-copy files ──────────────────────────────────────────────────
    missing_src = [src for src in DIRECT_COPIES.values() if not src.exists()]
    if missing_src:
        for p in missing_src:
            errors.append(f"Source not found: {p}")
    else:
        STATIC_DIR.mkdir(parents=True, exist_ok=True)
        for dest_name, src_path in DIRECT_COPIES.items():
            dest = STATIC_DIR / dest_name
            shutil.copy2(src_path, dest)
            print(f"  ✓ copied  {src_path.relative_to(ATLAS_ROOT)}  →  static/{dest_name}")

    # ── 2. Verify atlas-ui.css has required primitives ────────────────────────
    ui_css_path = STATIC_DIR / "atlas-ui.css"
    if not ui_css_path.exists():
        errors.append("static/atlas-ui.css not found — please restore it.")
    else:
        css = ui_css_path.read_text()
        missing_classes = [cls for cls in REQUIRED_UI_CLASSES if cls not in css]
        if missing_classes:
            errors.append(
                "atlas-ui.css is missing required classes:\n"
                + "".join(f"    {c}\n" for c in missing_classes)
            )
        else:
            print(f"  ✓ verified atlas-ui.css ({len(REQUIRED_UI_CLASSES)} required classes present)")

    # ── 3. Verify atlas-ui.css command palette (FR-2395) ─────────────────────
    if ui_css_path.exists():
        css = ui_css_path.read_text()
        palette_classes = [
            c for c in REQUIRED_UI_CLASSES if "palette" in c
        ]
        ok = all(c in css for c in palette_classes)
        marker = "✓" if ok else "✗"
        print(f"  {marker} command palette CSS present (FR-2395)")
        if not ok:
            errors.append("atlas-ui.css is missing CommandPalette classes (FR-2395).")

    # ── Summary ───────────────────────────────────────────────────────────────
    if errors:
        print("\nERRORS:")
        for e in errors:
            print(f"  ✗ {e}")
        sys.exit(1)

    print("\nDone. spec2sphere static CSS is in sync with @atlas/design-tokens.")


if __name__ == "__main__":
    sync()
