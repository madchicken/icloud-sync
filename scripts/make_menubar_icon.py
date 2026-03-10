#!/usr/bin/env python3
"""
Generate menubar template icons for iCloud Sync.
Run without arguments to apply the chosen variant.
Run with --preview to render all variants side by side.

Usage:
    python3 scripts/make_menubar_icon.py
    python3 scripts/make_menubar_icon.py --preview
"""
import sys
import cairosvg
from pathlib import Path

ROOT   = Path(__file__).parent.parent
ASSETS = ROOT / "assets"
ASSETS.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Icon variants — all drawn on a 44×44 viewBox, black on transparent
# ---------------------------------------------------------------------------

# Variant A: cloud + circular sync arrow (bidirectional feel)
VARIANT_A = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">
  <g fill="#000">
    <!-- Cloud -->
    <circle cx="15" cy="16" r="6.5"/>
    <circle cx="22" cy="12" r="8.5"/>
    <circle cx="29" cy="16" r="5.5"/>
    <rect x="9.5" y="15" width="25" height="7"/>
    <!-- Circular sync arrow -->
    <path d="M22 27 a7 7 0 1 1 -6.06 3.5" fill="none" stroke="#000" stroke-width="3" stroke-linecap="round"/>
    <polygon points="16,33 13,27 19,27"/>
  </g>
</svg>
"""

# Variant B: thin outlined cloud with up+down arrows inside
VARIANT_B = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">
  <g fill="none" stroke="#000" stroke-width="3" stroke-linejoin="round" stroke-linecap="round">
    <!-- Cloud outline -->
    <path d="M13 28 a8 8 0 0 1 1-16 9 9 0 0 1 16.5 3 6 6 0 0 1 -1 12"/>
  </g>
  <g fill="#000">
    <!-- Down arrow -->
    <rect x="23.5" y="20" width="3" height="8" rx="1"/>
    <polygon points="25,33 20,26 30,26"/>
    <!-- Up arrow -->
    <rect x="17.5" y="18" width="3" height="8" rx="1"/>
    <polygon points="19,14 14,21 24,21"/>
  </g>
</svg>
"""

# Variant C: minimal — just a clean cloud silhouette with a small sync dot
VARIANT_C = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">
  <g fill="#000">
    <!-- Slim cloud -->
    <circle cx="16" cy="22" r="7"/>
    <circle cx="24" cy="18" r="9"/>
    <circle cx="31" cy="22" r="6"/>
    <rect x="10" y="22" width="27" height="7"/>
    <!-- Two small arrows suggesting sync -->
    <path d="M17 34 a6 6 0 0 1 10 0" fill="none" stroke="#000" stroke-width="3" stroke-linecap="round"/>
    <polygon points="28,32 31,38 25,38"/>
    <polygon points="16,32 13,38 19,38"/>
  </g>
</svg>
"""

# Variant D: iCloud-style — rounded cloud, circular arrow below (clean)
VARIANT_D = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 44 44">
  <g fill="#000">
    <!-- Rounded cloud with smoother shape -->
    <path d="M34 23 a6 6 0 0 0 -5-5.9 10 10 0 0 0 -19.5 2.4 A6 6 0 0 0 11 31 h22 a6 6 0 0 0 1-8z"/>
    <!-- Circular sync arrow -->
    <path d="M22 34 a6 6 0 1 1 -5.2 3" fill="none" stroke="#000" stroke-width="2.5" stroke-linecap="round"/>
    <polygon points="16.8,39.5 14,33.5 20,33.5"/>
  </g>
</svg>
"""

VARIANTS = {
    "A": VARIANT_A,
    "B": VARIANT_B,
    "C": VARIANT_C,
    "D": VARIANT_D,
}

# Change this to pick which variant ships
CHOSEN = "D"  # noqa: use variant D


def render(svg: str, out: Path, size: int) -> None:
    cairosvg.svg2png(
        bytestring=svg.encode(),
        write_to=str(out),
        output_width=size,
        output_height=size,
    )


def preview_all() -> None:
    """Render all variants to /tmp so the user can compare."""
    out_dir = Path("/tmp/menubar-variants")
    out_dir.mkdir(exist_ok=True)
    for name, svg in VARIANTS.items():
        path = out_dir / f"variant_{name}.png"
        render(svg, path, 44)
        print(f"  Variant {name}: {path}")
    print(f"\nOpen with:  open {out_dir}")


def apply(variant: str) -> None:
    svg = VARIANTS[variant]
    swift_res = ROOT / "VirtualiCloud" / "VirtualiCloud" / "Resources"
    for dest in [ASSETS, swift_res]:
        if dest.exists():
            render(svg, dest / "menubarTemplate.png",    22)
            render(svg, dest / "menubarTemplate@2x.png", 44)
            print(f"  Written to {dest}")


if __name__ == "__main__":
    if "--preview" in sys.argv:
        print("Rendering all variants…")
        preview_all()
    else:
        print(f"Applying variant {CHOSEN}…")
        apply(CHOSEN)
        print("Done.")
