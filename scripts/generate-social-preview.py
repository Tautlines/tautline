#!/usr/bin/env python3
"""Render the GitHub social-preview PNG (docs/assets/social-preview.png).

Dev-only tool (see requirements-dev.txt: pillow). Not part of the CLI runtime,
which stays stdlib-only. Upload to GitHub Settings -> Social preview is a
manual, human-run operator step (Phase 3); this script only renders the file.

Usage:
    python3 scripts/generate-social-preview.py
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:  # pragma: no cover - operator-facing message, not exercised by tests
    print(
        "generate-social-preview: Pillow is required. Install it with:\n"
        "  pip install -r requirements-dev.txt",
        file=sys.stderr,
    )
    raise SystemExit(1) from None

WIDTH, HEIGHT = 1280, 640
OUTPUT = Path(__file__).resolve().parent.parent / "docs" / "assets" / "social-preview.png"

# Palette: near-black terminal background, a muted frame, and one bright accent
# used sparingly (the "green gate" color) so the wordmark carries the image.
BG = (11, 14, 20)
FRAME = (42, 47, 58)
FRAME_DIM = (28, 32, 40)
TITLE_TEXT = (140, 148, 163)
PROMPT_DIM = (90, 98, 112)
PROMPT_ACCENT = (61, 220, 132)  # green: "the gate is green"
WORDMARK = (237, 240, 245)
TAGLINE = (166, 173, 186)
TRAFFIC_RED = (255, 95, 86)
TRAFFIC_YELLOW = (255, 189, 46)
TRAFFIC_GREEN = (39, 201, 63)


def _font(candidates: list[str], size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default(size=size)


MONO_CANDIDATES = [
    "/System/Library/Fonts/SFNSMono.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/System/Library/Fonts/Supplemental/Andale Mono.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf",
]
MONO_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Courier New Bold.ttf",
    "/System/Library/Fonts/Menlo.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationMono-Bold.ttf",
]
SANS_BOLD_CANDIDATES = [
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Black.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
]


def render() -> Path:
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)

    # --- Subtle terminal-frame motif -----------------------------------
    margin = 56
    frame_box = (margin, margin, WIDTH - margin, HEIGHT - margin)
    titlebar_h = 44
    draw.rounded_rectangle(frame_box, radius=14, outline=FRAME, width=2, fill=None)
    titlebar_box = (frame_box[0], frame_box[1], frame_box[2], frame_box[1] + titlebar_h)
    draw.rounded_rectangle(titlebar_box, radius=14, fill=FRAME_DIM)
    # Square off the bottom corners of the titlebar so it reads as one piece
    # with the frame below it instead of a floating rounded pill.
    draw.rectangle((frame_box[0], frame_box[1] + titlebar_h - 14, frame_box[2], frame_box[1] + titlebar_h), fill=FRAME_DIM)

    dot_y = frame_box[1] + titlebar_h // 2
    dot_r = 6
    for i, color in enumerate((TRAFFIC_RED, TRAFFIC_YELLOW, TRAFFIC_GREEN)):
        dot_x = frame_box[0] + 24 + i * 22
        draw.ellipse((dot_x - dot_r, dot_y - dot_r, dot_x + dot_r, dot_y + dot_r), fill=color)

    title_font = _font(MONO_CANDIDATES, 16)
    title = "minervit-methodology"
    tb = draw.textbbox((0, 0), title, font=title_font)
    draw.text(
        ((frame_box[0] + frame_box[2]) / 2 - (tb[2] - tb[0]) / 2, dot_y - (tb[3] - tb[1]) / 2 - 2),
        title,
        font=title_font,
        fill=TITLE_TEXT,
    )

    # --- Terminal body content ------------------------------------------
    # Vertically center the (prompt, result, wordmark, tagline) block inside
    # the frame body so the card reads balanced instead of top-heavy.
    body_left = frame_box[0] + 48
    body_area_top = frame_box[1] + titlebar_h
    body_area_bottom = frame_box[3]

    prompt_font = _font(MONO_CANDIDATES, 22)
    prompt = "$ minervit-methodology guard-check --boundary prepush"
    result_font = _font(MONO_CANDIDATES, 22)
    result = "guard_check: ok"
    wordmark_font = _font(SANS_BOLD_CANDIDATES, 100)
    wordmark = "Minervit"
    tagline_font = _font(MONO_BOLD_CANDIDATES, 28)
    tagline = "Enforced completion gates for AI coding agents"

    prompt_h = draw.textbbox((0, 0), prompt, font=prompt_font)[3]
    result_h = draw.textbbox((0, 0), result, font=result_font)[3]
    wb = draw.textbbox((0, 0), wordmark, font=wordmark_font)
    wordmark_h = wb[3] - wb[1]
    tagline_h = draw.textbbox((0, 0), tagline, font=tagline_font)[3]

    gap_prompt_result = 12
    gap_result_wordmark = 56
    gap_wordmark_tagline = 36

    content_h = (
        prompt_h
        + gap_prompt_result
        + result_h
        + gap_result_wordmark
        + wordmark_h
        + gap_wordmark_tagline
        + tagline_h
    )
    y = body_area_top + ((body_area_bottom - body_area_top) - content_h) / 2

    draw.text((body_left, y), prompt, font=prompt_font, fill=PROMPT_DIM)
    y += prompt_h + gap_prompt_result
    draw.text((body_left, y), result, font=result_font, fill=PROMPT_ACCENT)
    y += result_h + gap_result_wordmark
    draw.text((body_left, y - wb[1]), wordmark, font=wordmark_font, fill=WORDMARK)
    y += wordmark_h + gap_wordmark_tagline
    draw.text((body_left, y), tagline, font=tagline_font, fill=TAGLINE)

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    img.save(OUTPUT, format="PNG")
    return OUTPUT


if __name__ == "__main__":
    path = render()
    print(f"generate-social-preview: wrote {path}")
