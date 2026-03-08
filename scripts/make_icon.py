#!/usr/bin/env python3
"""
Generate AppIcon.icns and the menu bar template image.

Draws a cloud icon using overlapping filled shapes (no extra dependencies —
only PyObjC, which is installed with rumps).

Usage (from the project root):
    python scripts/make_icon.py
"""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
ASSETS_DIR = ROOT / "assets"
ICONSET_DIR = ROOT / "AppIcon.iconset"


def _bootstrap_appkit():
    """NSImage rendering requires a running NSApplication."""
    from AppKit import NSApplication
    NSApplication.sharedApplication()


def _render_png(size: int, *, bg_rgba=None, cloud_rgba=(1.0, 1.0, 1.0, 1.0)) -> bytes:
    """
    Render a cloud icon to PNG bytes at *size* × *size* pixels.

    bg_rgba   – background colour (r,g,b,a) or None for transparent.
                When provided the background is drawn as a rounded rectangle.
    cloud_rgba – colour of the cloud shape.
    """
    from AppKit import (
        NSBezierPath, NSBitmapImageRep, NSColor, NSGraphicsContext,
        NSImage, NSMakeRect, NSMakeSize, NSPNGFileType,
    )

    image = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    image.lockFocus()

    ctx = NSGraphicsContext.currentContext()
    ctx.setShouldAntialias_(True)

    s = size / 100.0  # normalised → pixels

    # ── Background ────────────────────────────────────────────────────────────
    if bg_rgba:
        r, g, b, a = bg_rgba
        NSColor.colorWithRed_green_blue_alpha_(r, g, b, a).setFill()
        radius = size * 0.22
        NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
            NSMakeRect(0, 0, size, size), radius, radius
        ).fill()

    # ── Cloud shape (overlapping filled ovals + base rectangle) ──────────────
    r, g, b, a = cloud_rgba
    NSColor.colorWithRed_green_blue_alpha_(r, g, b, a).setFill()

    def oval(cx, cy, rx, ry):
        NSBezierPath.bezierPathWithOvalInRect_(
            NSMakeRect((cx - rx) * s, (cy - ry) * s, rx * 2 * s, ry * 2 * s)
        ).fill()

    # Base rectangle (bottom of cloud)
    NSBezierPath.fillRect_(NSMakeRect(12 * s, 24 * s, 76 * s, 22 * s))
    # Three bumps — left, centre (tallest), right
    oval(28, 42, 16, 16)
    oval(50, 56, 22, 22)
    oval(72, 40, 18, 18)

    image.unlockFocus()

    tiff = image.TIFFRepresentation()
    rep  = NSBitmapImageRep.imageRepWithData_(tiff)
    png  = rep.representationUsingType_properties_(NSPNGFileType, None)
    return bytes(png)


def make_icns():
    """Build AppIcon.icns from multiple sizes via iconutil."""
    _bootstrap_appkit()
    ICONSET_DIR.mkdir(exist_ok=True)

    # iCloud blue background + white cloud
    BG    = (0.22, 0.54, 0.97, 1.0)
    CLOUD = (1.0,  1.0,  1.0,  1.0)

    # iconutil expects these exact filenames
    for pt_size in (16, 32, 128, 256, 512):
        for scale, suffix in ((1, ""), (2, "@2x")):
            px = pt_size * scale
            data = _render_png(px, bg_rgba=BG, cloud_rgba=CLOUD)
            (ICONSET_DIR / f"icon_{pt_size}x{pt_size}{suffix}.png").write_bytes(data)
            print(f"  {pt_size}×{pt_size}{suffix}  ({px}px)")

    out = ROOT / "AppIcon.icns"
    subprocess.run(
        ["iconutil", "-c", "icns", str(ICONSET_DIR), "-o", str(out)],
        check=True,
    )
    shutil.rmtree(ICONSET_DIR)
    print(f"Created: {out}")


def make_menubar_template():
    """
    Create a menu bar template image: black cloud on transparent background.
    macOS tints template images automatically for dark / light mode.
    """
    _bootstrap_appkit()
    ASSETS_DIR.mkdir(exist_ok=True)

    BLACK = (0.0, 0.0, 0.0, 1.0)
    # 22 pt = standard menu bar height; provide @2x for Retina
    for pt, suffix in ((22, ""), (44, "@2x")):
        data = _render_png(pt, bg_rgba=None, cloud_rgba=BLACK)
        path = ASSETS_DIR / f"menubarTemplate{suffix}.png"
        path.write_bytes(data)
        print(f"Created: {path}")


if __name__ == "__main__":
    print("Generating app icon…")
    make_icns()
    print("Generating menu bar template…")
    make_menubar_template()
    print("Done.")
