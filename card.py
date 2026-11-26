"""Compose the GBVSR player card from puddle.farm artwork."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from io import BytesIO
from typing import Optional

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

# 高度 1080。宽度收在文字栏上，立绘从右侧伸进文字下方。
_BASE_W, _BASE_H = 760, 452
H = 1080
_SCALE = H / _BASE_H
W = round(_BASE_W * _SCALE)


def _u(value: float) -> int:
    return int(round(value * _SCALE))
BG = (14, 26, 40, 255)
TEXT = (231, 238, 243, 255)
MUTED = (154, 176, 194, 255)
GOLD = (232, 196, 122, 255)
LINE = (42, 68, 90, 255)
CHIP = (22, 44, 66, 255)
WIN = (88, 196, 146, 255)
LOSS = (224, 120, 136, 255)

_FONT_DIR = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
_YAHEI_BD = os.path.join(_FONT_DIR, "msyhbd.ttc")
_YAHEI = os.path.join(_FONT_DIR, "msyh.ttc")
_SEGOE_BD = os.path.join(_FONT_DIR, "segoeuib.ttf")
_SEGOE = os.path.join(_FONT_DIR, "segoeui.ttf")
_MALGUN_BD = os.path.join(_FONT_DIR, "malgunbd.ttf")
_MALGUN = os.path.join(_FONT_DIR, "malgun.ttf")


@dataclass
class CardData:
    name: str
    platform: str
    rank: str
    character: str
    mp: str
    global_rank: str
    character_rank: str
    win_rate: str
    wins: str
    losses: str
    matches: str
    season: str
    unit: str = "MP"
    art: Optional[Image.Image] = None
    rank_icon: Optional[Image.Image] = None
    sky: Optional[Image.Image] = None
    alts: list[Image.Image] = field(default_factory=list)


def open_image(data: bytes) -> Image.Image:
    with Image.open(BytesIO(data)) as image:
        return image.convert("RGBA")


def _font(size: int, *paths: str) -> ImageFont.ImageFont:
    for path in paths:
        if path and os.path.isfile(path):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def _fit_font(
    draw: ImageDraw.ImageDraw,
    text: str,
    max_width: int,
    start: int,
    minimum: int,
    *paths: str,
) -> ImageFont.ImageFont:
    size = start
    font = _font(size, *paths)
    while size > minimum and _text_size(draw, text, font)[0] > max_width:
        size -= 2
        font = _font(size, *paths)
    return font


def _name_fonts(name: str) -> tuple[str, ...]:
    if any("\uac00" <= ch <= "\ud7a3" for ch in name):
        return (_MALGUN_BD, _MALGUN, _YAHEI_BD, _YAHEI, _SEGOE_BD)
    if any(ord(ch) > 127 for ch in name):
        return (_YAHEI_BD, _YAHEI, _SEGOE_BD)
    return (_SEGOE_BD, _YAHEI_BD, _SEGOE)


def _paste(base: Image.Image, image: Image.Image, xy: tuple[int, int]) -> None:
    x, y = xy
    src_x = max(0, -x)
    src_y = max(0, -y)
    dest_x = max(0, x)
    dest_y = max(0, y)
    width = min(image.width - src_x, base.width - dest_x)
    height = min(image.height - src_y, base.height - dest_y)
    if width <= 0 or height <= 0:
        return
    piece = image.crop((src_x, src_y, src_x + width, src_y + height))
    base.alpha_composite(piece, (dest_x, dest_y))


def _content_box(image: Image.Image, threshold: int = 40) -> tuple[int, int, int, int]:
    """Opaque bounds, ignoring a thin fringe of stray pixels along the canvas edge."""
    alpha = image.getchannel("A")
    sample_w = 240
    sample_h = max(1, round(image.height * sample_w / image.width))
    sample = alpha.resize((sample_w, sample_h), Image.Resampling.BOX)
    pixels = sample.load()
    min_count = max(2, round(sample_w * 0.012))
    rows = [
        sum(pixels[x, y] > threshold for x in range(sample_w))
        for y in range(sample_h)
    ]
    cols = [
        sum(pixels[x, y] > threshold for y in range(sample_h))
        for x in range(sample_w)
    ]
    ys = [index for index, count in enumerate(rows) if count >= min_count]
    xs = [index for index, count in enumerate(cols) if count >= min_count]
    if not xs or not ys:
        return (0, 0, image.width, image.height)
    pad_x = max(2, round(image.width * 0.008))
    pad_y = max(2, round(image.height * 0.008))
    left = max(0, round(xs[0] * image.width / sample_w) - pad_x)
    top = max(0, round(ys[0] * image.height / sample_h) - pad_y)
    right = min(image.width, round((xs[-1] + 1) * image.width / sample_w) + pad_x)
    bottom = min(image.height, round((ys[-1] + 1) * image.height / sample_h) + pad_y)
    return (left, top, right, bottom)


def _place_art(base: Image.Image, art: Image.Image) -> None:
    """Fit the figure to the card height and park it on the right, under the text."""
    image = art.convert("RGBA")
    left, top, right, bottom = _content_box(image)
    content_w = max(1, right - left)
    content_h = max(1, bottom - top)
    pad_top = _u(14)
    pad_bottom = _u(8)
    pad_right = _u(12)
    max_w = max(1, W - pad_right)
    max_h = max(1, H - pad_top - pad_bottom)
    scale = min(max_w / content_w, max_h / content_h)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    content_right = round(right * scale)
    content_top = round(top * scale)
    content_bottom = round(bottom * scale)
    x = W - pad_right - content_right
    y = H - pad_bottom - content_bottom
    if y + content_top < pad_top:
        y = pad_top - content_top
    _paste(base, resized, (x, y))


def _cover(
    image: Image.Image,
    size: tuple[int, int],
    focus: tuple[float, float] = (0.5, 0.55),
) -> Image.Image:
    """Scale to fill size and crop around a focal point. Matches the site's object-position."""
    width, height = size
    scale = max(width / image.width, height / image.height)
    resized = image.resize(
        (max(1, round(image.width * scale)), max(1, round(image.height * scale))),
        Image.Resampling.LANCZOS,
    )
    left = round(min(max(focus[0], 0.0), 1.0) * resized.width - width / 2)
    top = round(min(max(focus[1], 0.0), 1.0) * resized.height - height / 2)
    left = min(max(left, 0), max(0, resized.width - width))
    top = min(max(top, 0), max(0, resized.height - height))
    return resized.crop((left, top, left + width, top + height))


def _paste_sky(base: Image.Image, sky: Image.Image, opacity: float = 0.9) -> None:
    covered = _cover(sky.convert("RGBA"), base.size, (0.5, 0.55))
    covered.putalpha(covered.getchannel("A").point(lambda value: int(value * opacity)))
    base.alpha_composite(covered)


def _left_scrim(
    base: Image.Image,
    solid_until: int,
    clear_at: int,
    color: tuple[int, int, int],
    max_alpha: int = 255,
) -> None:
    width, height = base.size
    row = Image.new("L", (width, 1), 0)
    pixels = row.load()
    span = max(clear_at - solid_until, 1)
    for x in range(width):
        if x <= solid_until:
            pixels[x, 0] = max_alpha
        elif x >= clear_at:
            pixels[x, 0] = 0
        else:
            t = (x - solid_until) / span
            t = t * t * (3 - 2 * t)
            pixels[x, 0] = int(max_alpha * (1 - t))
    mask = row.resize((width, height))
    veil = Image.new("RGBA", base.size, color + (255,))
    veil.putalpha(mask)
    base.alpha_composite(veil)


def _aa_disc(size: int, inset: int = 0, samples: int = 4) -> Image.Image:
    """Smooth ellipse mask. ImageDraw's ellipse is stair-stepped at 1x."""
    big = max(1, size * samples)
    pad = max(0, inset) * samples
    mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(mask).ellipse((pad, pad, big - 1 - pad, big - 1 - pad), fill=255)
    return mask.resize((size, size), Image.Resampling.LANCZOS)


def _aa_ring(size: int, width: int, color: tuple[int, int, int, int], samples: int = 4) -> Image.Image:
    big = max(1, size * samples)
    stroke = max(samples, width * samples)
    outer_mask = Image.new("L", (big, big), 0)
    inner_mask = Image.new("L", (big, big), 0)
    ImageDraw.Draw(outer_mask).ellipse((0, 0, big - 1, big - 1), fill=255)
    ImageDraw.Draw(inner_mask).ellipse(
        (stroke, stroke, big - 1 - stroke, big - 1 - stroke),
        fill=255,
    )
    ring_mask = ImageChops.subtract(outer_mask, inner_mask).resize(
        (size, size), Image.Resampling.LANCZOS
    )
    ring = Image.new("RGBA", (size, size), color[:3] + (0,))
    ring.putalpha(ring_mask)
    return ring


def _circle(image: Image.Image, size: int) -> Image.Image:
    icon = image.resize((size, size), Image.Resampling.LANCZOS)
    ring_w = max(2, size // 16)
    mask = _aa_disc(size, inset=max(1, ring_w // 2))
    circled = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circled.paste(icon, (0, 0), mask)
    circled.alpha_composite(_aa_ring(size, ring_w, GOLD))
    return circled


def _aa_rounded_rect(
    size: tuple[int, int],
    radius: int,
    fill: tuple[int, int, int, int],
    outline: Optional[tuple[int, int, int, int]] = None,
    outline_width: int = 0,
    samples: int = 4,
) -> Image.Image:
    width, height = size
    big = (max(1, width * samples), max(1, height * samples))
    image = Image.new("RGBA", big, (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    radius_px = max(0, radius * samples)
    if outline and outline_width > 0:
        stroke = max(samples, outline_width * samples)
        draw.rounded_rectangle((0, 0, big[0] - 1, big[1] - 1), radius=radius_px, fill=outline)
        draw.rounded_rectangle(
            (stroke, stroke, big[0] - 1 - stroke, big[1] - 1 - stroke),
            radius=max(0, radius_px - stroke),
            fill=fill,
        )
    else:
        draw.rounded_rectangle((0, 0, big[0] - 1, big[1] - 1), radius=radius_px, fill=fill)
    return image.resize(size, Image.Resampling.LANCZOS)


def render_card(data: CardData, out_path: str) -> None:
    canvas = Image.new("RGBA", (W, H), BG)
    has_sky = data.sky is not None
    if has_sky:
        _paste_sky(canvas, data.sky)
    elif data.art is not None:
        glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.ellipse(
            (W - _u(520), _u(10), W + _u(40), H + _u(40)),
            fill=(28, 78, 120, 90),
        )
        canvas.alpha_composite(glow.filter(ImageFilter.GaussianBlur(_u(28))))
    if has_sky:
        _left_scrim(canvas, _u(400), _u(620), (16, 36, 58), max_alpha=188)
    elif data.art is not None:
        _left_scrim(canvas, _u(430), _u(600), (14, 26, 40))
    if data.art is not None:
        _place_art(canvas, data.art)

    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, _u(5), H), fill=GOLD)

    f_kicker = _font(_u(14), _SEGOE, _YAHEI)
    f_mp = _font(_u(42), _SEGOE_BD, _YAHEI_BD, _SEGOE)
    f_unit = _font(_u(16), _SEGOE, _YAHEI)
    f_stat = _font(_u(24), _SEGOE_BD, _YAHEI_BD, _SEGOE)
    f_label = _font(_u(14), _YAHEI, _SEGOE)
    f_small = _font(_u(16), _YAHEI, _SEGOE)
    f_foot = _font(_u(13), _SEGOE, _YAHEI)

    x0 = _u(28)
    kicker = "GRANBLUE FANTASY VERSUS: RISING"
    draw.text((x0, _u(16)), kicker, font=f_kicker, fill=MUTED)
    if data.season:
        kicker_w, _ = _text_size(draw, kicker, f_kicker)
        draw.text(
            (x0 + kicker_w + _u(16), _u(16)),
            f"SEASON {data.season}",
            font=f_kicker,
            fill=GOLD,
        )

    name = data.name or "Unknown"
    name_y = _u(42)
    f_name = _fit_font(draw, name, _u(330), _u(40), _u(22), *_name_fonts(name))
    draw.text((x0, name_y), name, font=f_name, fill=TEXT)
    if data.platform:
        pill = data.platform
        pill_w, pill_h = _text_size(draw, pill, f_small)
        px = x0 + _text_size(draw, name, f_name)[0] + _u(12)
        py = name_y + _u(10)
        if px + pill_w + _u(20) <= _u(470):
            pill_size = (pill_w + _u(20), pill_h + _u(8))
            _paste(
                canvas,
                _aa_rounded_rect(pill_size, _u(7), (28, 58, 84, 255)),
                (px, py),
            )
            draw.text((px + _u(10), py + _u(2)), pill, font=f_small, fill=TEXT)

    rank_y = _u(108)
    text_x = x0
    if data.rank_icon is not None:
        icon = data.rank_icon.convert("RGBA").resize(
            (_u(78), _u(78)), Image.Resampling.LANCZOS
        )
        _paste(canvas, icon, (x0 - _u(4), rank_y))
        text_x = x0 + _u(82)
    rank_text = data.rank or "—"
    char_text = data.character or "—"
    text_max = max(_u(160), _u(450) - text_x)
    f_rank = _fit_font(
        draw, rank_text, text_max, _u(22), _u(14), _YAHEI_BD, _YAHEI, _SEGOE_BD
    )
    f_char = _fit_font(draw, char_text, text_max, _u(18), _u(12), _YAHEI, _SEGOE)
    draw.text((text_x, rank_y + _u(14)), rank_text, font=f_rank, fill=GOLD)
    draw.text((text_x, rank_y + _u(42)), char_text, font=f_char, fill=TEXT)

    mp_y = _u(198)
    mp_text = data.mp or "—"
    draw.text((x0, mp_y), mp_text, font=f_mp, fill=TEXT)
    mp_w, _ = _text_size(draw, mp_text, f_mp)
    if data.unit and mp_text != "—":
        draw.text((x0 + mp_w + _u(10), mp_y + _u(22)), data.unit, font=f_unit, fill=MUTED)

    rate_known = bool(data.win_rate) and data.win_rate != "—"
    chips = [
        (data.global_rank or "—", "全球排名", GOLD),
        (data.character_rank or "—", "角色排名", GOLD),
        (data.win_rate or "—", "胜率", WIN if rate_known else MUTED),
    ]
    chip_y = _u(258)
    chip_w, chip_h = _u(152), _u(68)
    gap = _u(10)
    for index, (value, label, color) in enumerate(chips):
        x = x0 + index * (chip_w + gap)
        _paste(
            canvas,
            _aa_rounded_rect(
                (chip_w, chip_h),
                _u(12),
                CHIP,
                outline=LINE,
                outline_width=max(1, _u(1)),
            ),
            (x, chip_y),
        )
        draw.text((x + _u(12), chip_y + _u(8)), value, font=f_stat, fill=color)
        draw.text((x + _u(12), chip_y + _u(38)), label, font=f_label, fill=MUTED)

    record_y = _u(342)
    if data.wins and data.losses:
        draw.text((x0, record_y), f"{data.wins}胜", font=f_small, fill=WIN)
        win_w, _ = _text_size(draw, f"{data.wins}胜", f_small)
        draw.text((x0 + win_w + _u(6), record_y), "/", font=f_small, fill=MUTED)
        slash_w, _ = _text_size(draw, "/", f_small)
        loss_x = x0 + win_w + _u(6) + slash_w + _u(6)
        draw.text((loss_x, record_y), f"{data.losses}负", font=f_small, fill=LOSS)
        loss_w, _ = _text_size(draw, f"{data.losses}负", f_small)
        tail_x = loss_x + loss_w + _u(16)
        if data.matches:
            draw.text((tail_x, record_y), f"·  {data.matches} 场", font=f_small, fill=MUTED)
    elif data.matches:
        draw.text((x0, record_y), f"{data.matches} 场", font=f_small, fill=MUTED)

    if data.alts:
        other_y = _u(376)
        label = "其他角色"
        draw.text((x0, other_y + _u(6)), label, font=f_label, fill=MUTED)
        label_w, _ = _text_size(draw, label, f_label)
        icon_size = _u(28)
        icon_x = x0 + label_w + _u(10)
        shown = 0
        for alt in data.alts:
            if icon_x + icon_size > _u(500):
                break
            _paste(canvas, _circle(alt, icon_size), (icon_x, other_y))
            icon_x += icon_size + _u(4)
            shown += 1
        hidden = len(data.alts) - shown
        if hidden > 0:
            draw.text((icon_x + _u(2), other_y + _u(5)), f"+{hidden}", font=f_small, fill=MUTED)

    draw.text((x0, H - _u(26)), "puddle.farm/gbvsr", font=f_foot, fill=(110, 132, 150, 255))

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rgb = Image.new("RGB", canvas.size, (14, 26, 40))
    rgb.paste(canvas, mask=canvas.getchannel("A"))
    rgb.save(out_path, "PNG", optimize=True)
