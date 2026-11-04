from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .battle import KING_HP, KING_POS, PRINCESS_HP, PRINCESS_POS

ARENA_PATH = Path(__file__).parent / "assets" / "arena.png"
WIDTH = 640
COLORS = [(52, 120, 246), (232, 64, 64)]
LANE_X = (0.383, 0.617)

_base = None
_fonts = {}


def _font(size: int):
    if size not in _fonts:
        try:
            _fonts[size] = ImageFont.truetype("DejaVuSans-Bold.ttf", size)
        except OSError:
            _fonts[size] = ImageFont.load_default()
    return _fonts[size]


def _arena() -> Image.Image:
    global _base
    if _base is None:
        img = Image.open(ARENA_PATH).convert("RGB")
        height = round(img.height * WIDTH / img.width)
        _base = img.resize((WIDTH, height), Image.LANCZOS)
    return _base.copy()


def _xy(img: Image.Image, lane: float, pos: float) -> tuple[int, int]:
    x = (0.5 if lane == 2 else LANE_X[int(lane)]) * img.width
    y = (0.731 - 0.405 * pos / 100) * img.height
    return round(x), round(y)


def _bar(draw, cx, top, width, ratio, color):
    left = cx - width // 2
    draw.rectangle([left, top, left + width, top + 5], fill=(30, 30, 30))
    draw.rectangle([left, top, left + round(width * max(0, ratio)), top + 5], fill=color)


def render(game) -> BytesIO:
    img = _arena()
    draw = ImageDraw.Draw(img)

    for side in (0, 1):
        for t in range(3):
            hp = game.sides[side].towers[t]
            pos = KING_POS[side] if t == 2 else PRINCESS_POS[side]
            cx, cy = _xy(img, t, pos)
            maximum = KING_HP if t == 2 else PRINCESS_HP
            w, h = (54, 42) if t == 2 else (44, 34)
            box = [cx - w // 2, cy - h // 2, cx + w // 2, cy + h // 2]
            if hp <= 0:
                draw.rounded_rectangle(box, 8, fill=(70, 70, 70), outline=(20, 20, 20), width=2)
                draw.text((cx, cy), "X", fill=(200, 200, 200), font=_font(18), anchor="mm")
                continue
            draw.rounded_rectangle(box, 8, fill=COLORS[side], outline=(255, 255, 255), width=2)
            draw.text((cx, cy - 2), "K" if t == 2 else "P", fill="white", font=_font(16), anchor="mm")
            _bar(draw, cx, box[3] + 3, w, hp / maximum, (90, 230, 90))

    stacks = {}
    for unit in game.units:
        key = (unit.lane, unit.side)
        index = stacks.get(key, 0)
        stacks[key] = index + 1
        cx, cy = _xy(img, unit.lane, unit.pos)
        cx += ((index % 3) - 1) * 16
        cy += (index // 3) * 8
        draw.ellipse([cx - 15, cy - 15, cx + 15, cy + 15], fill=COLORS[unit.side], outline="white", width=2)
        draw.text((cx, cy), unit.name[:3].upper(), fill="white", font=_font(11), anchor="mm")
        _bar(draw, cx, cy - 23, 28, unit.hp / unit.max_hp, (90, 230, 90))

    out = BytesIO()
    img.save(out, "JPEG", quality=82)
    out.seek(0)
    return out
