"""UtiliVault Field — brand asset generator.

The mark: a vault-dial ring (safe dial with tick marks — "Vault") holding a
water droplet ("Utili[ty]"), amber on deep navy. Palette matches
src/theme.js exactly.

Outputs (into ./assets):
    icon.png           1024x1024  app icon (rounded look supplied by OS)
    adaptive-icon.png  1024x1024  Android foreground (mark in the 66% safe zone)
    splash.png         1242x2436  mark + wordmark
    favicon.png        48x48      web favicon

Run:  py generate_assets.py
"""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).parent / "assets"
ASSETS.mkdir(exist_ok=True)

# --- palette (mirrors src/theme.js) -----------------------------------------
BG_DEEP = (7, 12, 19)        # a hair darker than app bg for icon depth
BG = (11, 19, 30)            # #0b131e
PANEL = (19, 30, 44)         # #131e2c
AMBER = (240, 180, 41)       # #f0b429
AMBER_DARK = (183, 133, 20)  # #b78514
TEXT = (242, 246, 250)       # #f2f6fa
TEXT_DIM = (147, 167, 187)   # #93a7bb

SS = 4  # supersample factor for crisp curves


def radial_bg(size, inner, outer):
    """Square canvas with a radial gradient, center-weighted."""
    img = Image.new("RGB", (size, size), outer)
    px = img.load()
    cx = cy = size / 2
    maxd = math.hypot(cx, cy)
    for y in range(size):
        for x in range(size):
            t = min(math.hypot(x - cx, y - cy) / maxd, 1.0)
            t = t ** 1.6
            px[x, y] = tuple(round(inner[i] * (1 - t) + outer[i] * t) for i in range(3))
    return img


def droplet_points(cx, cy, r, steps=240):
    """Teardrop: parametric — circle bottom, curved point top."""
    pts = []
    for i in range(steps + 1):
        t = math.pi * (i / steps)  # 0..pi, right half top->bottom
        x = r * math.sin(t) * math.sin(t / 2) ** 0.7
        y = -r * math.cos(t)
        pts.append((cx + x, cy + y * 1.15))
    for i in range(steps + 1):
        t = math.pi * (1 - i / steps)
        x = r * math.sin(t) * math.sin(t / 2) ** 0.7
        y = -r * math.cos(t)
        pts.append((cx - x, cy + y * 1.15))
    return pts


def draw_mark(draw, cx, cy, R, ss=1):
    """Vault dial + droplet, scaled so the dial's outer radius is R."""
    ring_w = R * 0.085 * ss and max(round(R * 0.085), 2)
    # Outer ring
    draw.ellipse([cx - R, cy - R, cx + R, cy + R],
                 outline=AMBER, width=ring_w)
    # Dial tick marks — 12 stubs just inside the ring, like a safe dial
    tick_r1 = R * 0.86
    tick_r2 = R * 0.74
    tick_w = max(round(R * 0.045), 2)
    for k in range(12):
        a = math.radians(k * 30 - 90)
        # Skip ticks at the droplet's widest span for breathing room? Keep all.
        x1, y1 = cx + tick_r1 * math.cos(a), cy + tick_r1 * math.sin(a)
        x2, y2 = cx + tick_r2 * math.cos(a), cy + tick_r2 * math.sin(a)
        col = AMBER if k % 3 == 0 else AMBER_DARK
        draw.line([x1, y1, x2, y2], fill=col, width=tick_w)
    # Droplet, centered, sized to sit inside the tick circle
    dr = R * 0.44
    dy = cy + R * 0.06
    pts = droplet_points(cx, dy, dr)
    draw.polygon(pts, fill=AMBER)
    # Keyhole cutout, centered in the bulb — vault + water in one mark.
    kr = dr * 0.20                       # keyhole circle radius
    ky = dy + dr * 0.08                  # circle center, middle of the bulb
    draw.ellipse([cx - kr, ky - kr, cx + kr, ky + kr], fill=BG_DEEP)
    stem_top = kr * 0.45                 # stem flares downward from the circle
    stem_bot = kr * 0.85
    stem_len = dr * 0.52
    draw.polygon([
        (cx - stem_top, ky + kr * 0.5),
        (cx + stem_top, ky + kr * 0.5),
        (cx + stem_bot, ky + kr * 0.5 + stem_len),
        (cx - stem_bot, ky + kr * 0.5 + stem_len),
    ], fill=BG_DEEP)


def make_icon():
    size = 1024 * SS
    img = radial_bg(1024, PANEL, BG_DEEP).resize((size, size), Image.LANCZOS)
    d = ImageDraw.Draw(img)
    draw_mark(d, size / 2, size / 2, size * 0.335, ss=SS)
    img = img.resize((1024, 1024), Image.LANCZOS)
    img.save(ASSETS / "icon.png")
    img.resize((48, 48), Image.LANCZOS).save(ASSETS / "favicon.png")


def make_adaptive():
    # Foreground layer: transparent, mark inside the 66% safe zone.
    size = 1024 * SS
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    draw_mark(d, size / 2, size / 2, size * 0.26, ss=SS)
    img = img.resize((1024, 1024), Image.LANCZOS)
    img.save(ASSETS / "adaptive-icon.png")


def font(path_candidates, px):
    for p in path_candidates:
        try:
            return ImageFont.truetype(p, px)
        except OSError:
            continue
    return ImageFont.load_default()


def spaced_text(draw, xy, text, fnt, fill, tracking, anchor_center_x=None):
    """Draw text with letter-spacing; optionally centered on anchor_center_x."""
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = (anchor_center_x - total / 2) if anchor_center_x is not None else xy[0]
    y = xy[1]
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += w + tracking
    return total


def make_splash():
    W, H = 1242, 2436
    # Full-canvas radial glow centered on the mark — no paste seams.
    img = Image.new("RGB", (W, H), BG)
    px = img.load()
    gcx, gcy = W / 2, H * 0.40
    reach = W * 0.85
    for y in range(H):
        for x in range(W):
            t = min(math.hypot(x - gcx, y - gcy) / reach, 1.0) ** 1.5
            px[x, y] = tuple(round(PANEL[i] * (1 - t) + BG[i] * t) for i in range(3))

    big = Image.new("RGBA", (W * 2, W * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(big)
    draw_mark(d, W, W, W * 0.42, ss=2)
    mark = big.resize((round(W * 0.5), round(W * 0.5)), Image.LANCZOS)
    mx = (W - mark.width) // 2
    my = round(H * 0.30)
    img.paste(mark, (mx, my), mark)

    d = ImageDraw.Draw(img)
    # Bahnschrift = Windows' DIN — engineered, municipal, fits a utility app.
    f_word = font(["C:/Windows/Fonts/bahnschrift.ttf",
                   "C:/Windows/Fonts/arialbd.ttf"], 108)
    f_sub = font(["C:/Windows/Fonts/bahnschrift.ttf",
                  "C:/Windows/Fonts/arial.ttf"], 44)
    f_tag = font(["C:/Windows/Fonts/segoeui.ttf",
                  "C:/Windows/Fonts/arial.ttf"], 34)

    y = my + mark.height + 110
    spaced_text(d, (0, y), "UTILIVAULT", f_word, TEXT, tracking=14, anchor_center_x=W / 2)
    y += 132
    spaced_text(d, (0, y), "FIELD", f_sub, AMBER, tracking=30, anchor_center_x=W / 2)
    y += 92
    spaced_text(d, (0, y), "Example Utility · Water Service Records", f_tag, TEXT_DIM,
                tracking=2, anchor_center_x=W / 2)

    img.save(ASSETS / "splash.png")


if __name__ == "__main__":
    make_icon()
    make_adaptive()
    make_splash()
    for f in ["icon.png", "adaptive-icon.png", "splash.png", "favicon.png"]:
        print(f"wrote assets/{f}")
