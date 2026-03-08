#!/usr/bin/env python3
"""
Generate AppIcon.icns and menu bar template images from iCloud-sync-icon.png.

Uses only macOS built-in tools (sips, iconutil) — no Python dependencies.

Usage (from the project root):
    python3 scripts/make_icon.py
"""
import shutil
import subprocess
from pathlib import Path

ROOT       = Path(__file__).parent.parent
SOURCE_PNG = ROOT / "iCloud-sync-icon.png"
ASSETS_DIR = ROOT / "assets"
ICONSET_DIR = ROOT / "AppIcon.iconset"


def make_icns() -> None:
    """Build AppIcon.icns from the source PNG via iconutil."""
    ICONSET_DIR.mkdir(exist_ok=True)

    # iconutil expects these exact filenames
    for pt_size in (16, 32, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            px = pt_size * scale
            out = ICONSET_DIR / f"icon_{pt_size}x{pt_size}{suffix}.png"
            subprocess.run(
                ["sips", "-z", str(px), str(px), str(SOURCE_PNG), "--out", str(out)],
                check=True, capture_output=True,
            )
            print(f"  {pt_size}×{pt_size}{suffix}  ({px}px)")

    out = ROOT / "AppIcon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(out)],
        check=True,
    )
    shutil.rmtree(ICONSET_DIR)
    print(f"Created: {out}")


def make_menubar_template() -> None:
    """
    Resize the source PNG to menu bar sizes.

    macOS renders template images as a silhouette using the alpha channel,
    so colours in the source are ignored — only the shape matters.
    """
    ASSETS_DIR.mkdir(exist_ok=True)

    for px, suffix in ((22, ""), (44, "@2x")):
        out = ASSETS_DIR / f"menubarTemplate{suffix}.png"
        subprocess.run(
            ["sips", "-z", str(px), str(px), str(SOURCE_PNG), "--out", str(out)],
            check=True, capture_output=True,
        )
        print(f"Created: {out}")


if __name__ == "__main__":
    if not SOURCE_PNG.exists():
        raise SystemExit(f"Source image not found: {SOURCE_PNG}\n"
                         f"Place your icon PNG at {SOURCE_PNG} and re-run.")
    print("Generating app icon…")
    make_icns()
    print("Generating menu bar template…")
    make_menubar_template()
    print("Done.")
