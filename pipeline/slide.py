"""Branded key-points slide, rendered with Pillow (Phase 4).

1920x1080 (or matching the meeting video's size), CAIC blue palette,
meeting title + date + key points with timestamps.
"""

import textwrap
from pathlib import Path

from . import config

FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_REG = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def render_slide(title: str, date: str, key_points: list, out_path: str,
                 size=(1920, 1080)) -> str:
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    s = w / 1920  # scale everything relative to 1080p design
    img = Image.new("RGB", size, config.BRAND["navy"])
    d = ImageDraw.Draw(img)

    # accent bar + header
    d.rectangle([0, 0, w, int(8 * s)], fill=config.BRAND["accent"])
    f_small = ImageFont.truetype(FONT_REG, int(34 * s))
    f_title = ImageFont.truetype(FONT_BOLD, int(64 * s))
    f_point = ImageFont.truetype(FONT_REG, int(38 * s))
    f_ts = ImageFont.truetype(FONT_BOLD, int(28 * s))

    x = int(120 * s)
    d.text((x, int(70 * s)), "CINCINNATI AI CATALYST",
           font=f_small, fill=config.BRAND["accent"])
    y = int(130 * s)
    for line in textwrap.wrap(title, width=42)[:2]:
        d.text((x, y), line, font=f_title, fill="#ffffff")
        y += int(80 * s)
    d.text((x, y + int(4 * s)), date, font=f_small, fill="#9cc5dd")
    y += int(90 * s)

    # key points (max 5, wrapped)
    for kp in key_points[:5]:
        ts = kp.get("timestamp")
        d.ellipse([x, y + int(14 * s), x + int(16 * s), y + int(30 * s)],
                  fill=config.BRAND["accent"])
        tx = x + int(44 * s)
        if ts:
            d.text((tx, y + int(6 * s)), ts, font=f_ts,
                   fill=config.BRAND["accent"])
            tx += int(d.textlength(ts, font=f_ts)) + int(24 * s)
        lines = textwrap.wrap(kp["text"], width=64)[:2]
        for i, line in enumerate(lines):
            d.text((tx if i == 0 else x + int(44 * s), y + i * int(48 * s)),
                   line, font=f_point, fill="#e6eef4")
        y += int(48 * s) * len(lines) + int(28 * s)
        if y > h - int(140 * s):
            break

    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path


def render_intro_placeholder(out_path: str, size=(1920, 1080)) -> str:
    """Simple title card used until the real assets/caic_intro.mp4 exists."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = size
    s = w / 1920
    img = Image.new("RGB", size, config.BRAND["blue"])
    d = ImageDraw.Draw(img)
    f1 = ImageFont.truetype(FONT_BOLD, int(96 * s))
    f2 = ImageFont.truetype(FONT_REG, int(40 * s))
    t1, t2 = "Cincinnati AI Catalyst", "Meeting Recording"
    w1 = d.textlength(t1, font=f1)
    w2 = d.textlength(t2, font=f2)
    d.text(((w - w1) / 2, h / 2 - int(90 * s)), t1, font=f1, fill="#ffffff")
    d.text(((w - w2) / 2, h / 2 + int(40 * s)), t2, font=f2, fill="#9cc5dd")
    d.rectangle([0, h - int(12 * s), w, h], fill=config.BRAND["accent"])
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path)
    return out_path
