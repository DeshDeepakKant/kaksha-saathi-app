"""Draws the Kaksha Saathi app icons (an owl): python3 tools/make_app_icons.py

Per app it writes, into apps/<app>/assets/icon/:
  icon.png            1024 full-bleed square (legacy Android, web)
  icon_foreground.png 1024 transparent, owl inside the adaptive-icon safe zone
  icon_mono.png       1024 white-on-transparent silhouette (Android 13+ themed icons)
`flutter_launcher_icons` turns them into every size (see each app's pubspec.yaml).
Needs Pillow (the backend venv has it).
"""
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
S = 4096  # draw big, shrink for clean edges
INK = (29, 43, 42)
TAN = (201, 143, 79)
WING = (154, 101, 53)
CREAM = (248, 233, 204)
EYE = (255, 247, 228)
AMBER = (231, 161, 59)
BEAK = (242, 158, 56)
APPS = {  # background, has a graduation cap
    "parent": ((15, 107, 92), False),
    "teacher": ((30, 75, 107), True),
}


def ell(d, cx, cy, rx, ry, fill, outline=None, width=0):
    d.ellipse([cx - rx, cy - ry, cx + rx, cy + ry], fill=fill, outline=outline, width=width)


def owl(d, cx, cy, w, cap=False, mono=None):
    """Draw the owl centred on (cx, cy), `w` wide. With `mono`, draw a one-colour mask instead:
    mono=(body, hole) fills (255, 0)."""
    def c(color, m):
        return m if mono else color
    body_m, hole_m = (255, 0) if mono else (None, None)
    h = 1.12 * w
    top = cy - h / 2
    if not cap:  # ear tufts
        for sx in (-1, 1):
            d.polygon([(cx + sx * 0.46 * w, top + 0.10 * w), (cx + sx * 0.40 * w, top - 0.12 * w),
                       (cx + sx * 0.16 * w, top + 0.04 * w)], fill=c(TAN, body_m))
    # wings (behind), body, belly
    for sx in (-1, 1):
        ell(d, cx + sx * 0.47 * w, cy + 0.10 * w, 0.13 * w, 0.30 * w, c(WING, body_m))
    ell(d, cx, cy, 0.5 * w, h / 2, c(TAN, body_m))
    if not mono:
        ell(d, cx, cy + 0.20 * w, 0.30 * w, 0.34 * w, CREAM)
        for i, yy in enumerate((0.06, 0.20, 0.34)):  # feather marks
            for sx in (-0.11, 0.11):
                d.arc([cx + sx * w - 0.05 * w, cy + yy * w + 0.04 * w, cx + sx * w + 0.05 * w, cy + yy * w + 0.14 * w],
                      200, 340, fill=TAN, width=int(0.014 * w))
    # eyes
    ey = cy - 0.17 * w
    for sx in (-1, 1):
        ex = cx + sx * 0.2 * w
        if mono:
            ell(d, ex, ey, 0.17 * w, 0.17 * w, hole_m)
            ell(d, ex, ey, 0.075 * w, 0.075 * w, body_m)
        else:
            ell(d, ex, ey, 0.205 * w, 0.205 * w, AMBER)
            ell(d, ex, ey, 0.17 * w, 0.17 * w, EYE)
            ell(d, ex + sx * 0.012 * w, ey + 0.01 * w, 0.085 * w, 0.085 * w, INK)
            ell(d, ex + sx * 0.012 * w - 0.025 * w, ey - 0.02 * w, 0.028 * w, 0.028 * w, (255, 255, 255))
    # beak
    d.polygon([(cx - 0.065 * w, ey + 0.10 * w), (cx + 0.065 * w, ey + 0.10 * w), (cx, ey + 0.25 * w)],
              fill=c(BEAK, hole_m if mono else None) if not mono else hole_m)
    # feet
    if not mono:
        for sx in (-1, 1):
            for k in (-1, 0, 1):
                ell(d, cx + sx * 0.18 * w + k * 0.055 * w, cy + h / 2 - 0.005 * w, 0.03 * w, 0.045 * w, BEAK)
    if cap:  # graduation cap: board, base, tassel
        col = c(INK, body_m)
        base_top = top + 0.14 * w
        d.polygon([(cx - 0.30 * w, base_top), (cx + 0.30 * w, base_top), (cx + 0.24 * w, base_top + 0.17 * w),
                   (cx - 0.24 * w, base_top + 0.17 * w)], fill=col)
        d.polygon([(cx - 0.62 * w, base_top - 0.03 * w), (cx, base_top - 0.24 * w),
                   (cx + 0.62 * w, base_top - 0.03 * w), (cx, base_top + 0.12 * w)], fill=col)
        if not mono:
            d.line([(cx + 0.50 * w, base_top - 0.02 * w), (cx + 0.50 * w, base_top + 0.26 * w)], fill=AMBER, width=int(0.022 * w))
            ell(d, cx + 0.50 * w, base_top + 0.29 * w, 0.035 * w, 0.045 * w, AMBER)


def render(kind, bg, cap):
    out = ROOT / "apps" / kind / "assets" / "icon"
    out.mkdir(parents=True, exist_ok=True)
    centre = S // 2
    # full-bleed: soft teal gradient behind a big owl
    img = Image.new("RGB", (S, S), bg)
    px = ImageDraw.Draw(img)
    for y in range(S):  # light vertical gradient, lighter at the top
        t = y / S
        px.line([(0, y), (S, y)], fill=tuple(int(v * (1.18 - 0.30 * t)) if v * (1.18 - 0.30 * t) < 255 else 255 for v in bg))
    owl(ImageDraw.Draw(img), centre, centre + int(0.03 * S), int(0.56 * S), cap=cap)
    img.resize((1024, 1024), Image.LANCZOS).save(out / "icon.png")
    # adaptive foreground: owl inside the central ~56% (safe zone is 61%)
    fg = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    owl(ImageDraw.Draw(fg), centre, centre + int(0.02 * S), int(0.40 * S), cap=cap)
    fg.resize((1024, 1024), Image.LANCZOS).save(out / "icon_foreground.png")
    # themed (monochrome): alpha mask of the owl with eyes and beak as holes
    mask = Image.new("L", (S, S), 0)
    owl(ImageDraw.Draw(mask), centre, centre + int(0.02 * S), int(0.40 * S), cap=cap, mono=True)
    white = Image.new("RGBA", (S, S), (255, 255, 255, 0))
    white.putalpha(mask)
    white.resize((1024, 1024), Image.LANCZOS).save(out / "icon_mono.png")
    print("wrote", out)


if __name__ == "__main__":
    for kind, (bg, cap) in APPS.items():
        render(kind, bg, cap)
