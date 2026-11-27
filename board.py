"""Leaderboard and win-rate images."""

from __future__ import annotations

import os
import sys
from typing import Optional

from PIL import Image, ImageDraw

_DIR = os.path.dirname(os.path.abspath(__file__))
if _DIR not in sys.path:
    sys.path.insert(0, _DIR)

from card import (  # noqa: E402
    BG,
    GOLD,
    LOSS,
    MUTED,
    TEXT,
    WIN,
    _SEGOE,
    _SEGOE_BD,
    _YAHEI,
    _YAHEI_BD,
    _aa_disc,
    _circle,
    _font,
    font_for,
    _paste,
    _paste_sky,
    _text_size,
)

_SCALE = 2


def _p(value: float) -> int:
    return int(round(value * _SCALE))


_WIDTH = _p(880)


def _ellipsis(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> str:
    if _text_size(draw, text, font)[0] <= max_width:
        return text
    trimmed = text
    while trimmed and _text_size(draw, trimmed + "…", font)[0] > max_width:
        trimmed = trimmed[:-1]
    return (trimmed + "…") if trimmed else "…"


def _rate_color(rate: str) -> tuple[int, int, int, int]:
    try:
        value = float(rate.replace("%", "").replace(",", "").strip())
    except ValueError:
        return TEXT
    if value >= 53:
        return WIN
    if value <= 47:
        return LOSS
    return TEXT


def _prepare(width: int, height: int, sky: Optional[Image.Image]) -> Image.Image:
    canvas = Image.new("RGBA", (width, height), BG)
    if sky is not None:
        _paste_sky(canvas, sky, opacity=0.42)
        veil = Image.new("RGBA", canvas.size, (12, 24, 38, 188))
        canvas.alpha_composite(veil)
    return canvas


def _finish(canvas: Image.Image, out_path: str) -> None:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    rgb = Image.new("RGB", canvas.size, (14, 26, 40))
    rgb.paste(canvas, mask=canvas.getchannel("A"))
    rgb.save(out_path, "PNG", optimize=True)


def _header(canvas: Image.Image, title: str, subtitle: str) -> int:
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, _p(5), canvas.height), fill=GOLD)
    kicker_font = _font(_p(13), _SEGOE, _YAHEI)
    title_font = _font(_p(28), _YAHEI_BD, _SEGOE_BD)
    sub_font = _font(_p(15), _YAHEI, _SEGOE)
    x = _p(28)
    draw.text((x, _p(18)), "GRANBLUE FANTASY VERSUS: RISING", font=kicker_font, fill=MUTED)
    draw.text((x, _p(42)), title, font=title_font, fill=TEXT)
    draw.text((x, _p(82)), subtitle, font=sub_font, fill=GOLD)
    return _p(118)


def _footer(canvas: Image.Image, y: int, updated: str = "") -> None:
    draw = ImageDraw.Draw(canvas)
    font = _font(_p(12), _YAHEI, _SEGOE)
    ink = (110, 132, 150, 255)
    if updated:
        draw.text((_p(28), y), f"数据更新 {updated}", font=font, fill=ink)
        credit = "puddle.farm/gbvsr"
        credit_w = _text_size(draw, credit, font)[0]
        draw.text((_WIDTH - _p(28) - credit_w, y), credit, font=font, fill=ink)
        return
    draw.text((_p(28), y), "puddle.farm/gbvsr", font=font, fill=ink)


def render_leaderboard(
    rows: list,
    out_path: str,
    title: str,
    subtitle: str,
    portraits: dict[str, Image.Image],
    rank_icons: dict[str, Image.Image],
    sky: Optional[Image.Image] = None,
    character_zh=None,
    rank_zh=None,
    updated: str = "",
) -> None:
    row_h = _p(52)
    height = _p(118) + row_h * max(1, len(rows)) + _p(42)
    canvas = _prepare(_WIDTH, height, sky)
    y = _header(canvas, title, subtitle)
    draw = ImageDraw.Draw(canvas)
    num_font = _font(_p(16), _SEGOE_BD, _YAHEI_BD)
    body_font = _font(_p(15), _YAHEI, _SEGOE)
    small_font = _font(_p(12), _YAHEI, _SEGOE)
    pos_font = _font(_p(18), _SEGOE_BD, _YAHEI_BD)
    icon = _p(34)
    for index, row in enumerate(rows):
        if index % 2 == 0:
            draw.rectangle(( _p(16), y, _WIDTH - _p(16), y + row_h - _p(6)), fill=(18, 40, 60, 210))
        pos = str(row.position)
        pos_color = GOLD if row.position <= 3 else TEXT
        draw.text((_p(28), y + _p(12)), pos, font=pos_font, fill=pos_color)
        name_font = font_for(_p(16), row.name or "", bold=True)
        name = _ellipsis(draw, row.name or "—", name_font, _p(250))
        draw.text((_p(78), y + _p(6)), name, font=name_font, fill=TEXT)
        platform = row.platform or ""
        if platform:
            draw.text((_p(78), y + _p(28)), platform, font=small_font, fill=MUTED)
        character = character_zh(row.character) if character_zh else row.character
        portrait = portraits.get(row.portrait_url)
        text_x = _p(360)
        if portrait is not None:
            _paste(canvas, _circle(portrait, icon), (_p(352), y + _p(6)))
            text_x = _p(394)
        draw.text(
            (text_x, y + _p(14)),
            _ellipsis(draw, character or "—", body_font, _p(150)),
            font=body_font,
            fill=TEXT,
        )
        rank_name = rank_zh(row.rank) if rank_zh else row.rank
        rank_icon = rank_icons.get(row.rank_icon_url)
        rank_x = _p(560)
        if rank_icon is not None:
            _paste(
                canvas,
                rank_icon.convert("RGBA").resize((icon, icon), Image.Resampling.LANCZOS),
                (_p(556), y + _p(6)),
            )
            rank_x = _p(596)
        draw.text(
            (rank_x, y + _p(14)),
            _ellipsis(draw, rank_name or "—", body_font, _p(130)),
            font=body_font,
            fill=GOLD,
        )
        mp = row.mp or "—"
        mp_w = _text_size(draw, mp, num_font)[0]
        draw.text((_WIDTH - _p(28) - mp_w, y + _p(8)), mp, font=num_font, fill=TEXT)
        unit = "MP"
        unit_w = _text_size(draw, unit, small_font)[0]
        draw.text((_WIDTH - _p(28) - unit_w, y + _p(28)), unit, font=small_font, fill=MUTED)
        y += row_h
    _footer(canvas, y + _p(4), updated)
    _finish(canvas, out_path)


def render_rates(
    rows: list,
    out_path: str,
    title: str,
    subtitle: str,
    portraits: dict[str, Image.Image],
    sky: Optional[Image.Image] = None,
    character_zh=None,
    show_wins: bool = False,
    updated: str = "",
) -> None:
    row_h = _p(44)
    height = _p(118) + row_h * max(1, len(rows)) + _p(42)
    canvas = _prepare(_WIDTH, height, sky)
    y = _header(canvas, title, subtitle)
    draw = ImageDraw.Draw(canvas)
    name_font = _font(_p(16), _YAHEI, _SEGOE)
    rate_font = _font(_p(16), _YAHEI_BD, _SEGOE_BD)
    small_font = _font(_p(13), _YAHEI, _SEGOE)
    icon = _p(32)
    bar_w = _p(150)
    for index, row in enumerate(rows):
        if index % 2 == 0:
            draw.rectangle((_p(16), y, _WIDTH - _p(16), y + row_h - _p(4)), fill=(18, 40, 60, 210))
        portrait = portraits.get(row.portrait_url)
        text_x = _p(28)
        if portrait is not None:
            _paste(canvas, _circle(portrait, icon), (_p(24), y + _p(4)))
            text_x = _p(64)
        label = character_zh(row.character) if character_zh else row.character
        draw.text(
            (text_x, y + _p(10)),
            _ellipsis(draw, label or "—", name_font, _p(220)),
            font=name_font,
            fill=TEXT,
        )
        rate = row.win_rate or "—"
        try:
            value = float(rate.replace("%", "").replace(",", "").strip())
        except ValueError:
            value = 0
        bar_x = _p(320)
        bar_y = y + _p(16)
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_w, bar_y + _p(10)),
            radius=_p(5),
            fill=(28, 52, 74, 255),
        )
        fill_w = max(0, min(bar_w, int(bar_w * value / 100)))
        if fill_w > 0:
            draw.rounded_rectangle(
                (bar_x, bar_y, bar_x + fill_w, bar_y + _p(10)),
                radius=_p(5),
                fill=_rate_color(rate),
            )
        draw.text((bar_x + bar_w + _p(14), y + _p(8)), rate, font=rate_font, fill=_rate_color(rate))
        if show_wins:
            detail = f"{row.wins}胜 / {row.matches}场"
        else:
            detail = f"{row.matches}场"
        detail_w = _text_size(draw, detail, small_font)[0]
        draw.text((_WIDTH - _p(28) - detail_w, y + _p(12)), detail, font=small_font, fill=MUTED)
        y += row_h
    _footer(canvas, y + _p(4), updated)
    _finish(canvas, out_path)


def _share_value(share: str) -> float:
    try:
        return float(share.replace("%", "").replace(",", "").strip())
    except ValueError:
        return 0.0


def render_usage(
    rows: list,
    out_path: str,
    title: str,
    subtitle: str,
    portraits: dict[str, Image.Image],
    sky: Optional[Image.Image] = None,
    character_zh=None,
    updated: str = "",
) -> None:
    row_h = _p(44)
    height = _p(118) + row_h * max(1, len(rows)) + _p(42)
    canvas = _prepare(_WIDTH, height, sky)
    y = _header(canvas, title, subtitle)
    draw = ImageDraw.Draw(canvas)
    name_font = _font(_p(16), _YAHEI, _SEGOE)
    rate_font = _font(_p(16), _YAHEI_BD, _SEGOE_BD)
    small_font = _font(_p(13), _YAHEI, _SEGOE)
    icon = _p(32)
    bar_w = _p(150)
    peak = max((_share_value(row.share) for row in rows), default=0.0)
    for index, row in enumerate(rows):
        if index % 2 == 0:
            draw.rectangle((_p(16), y, _WIDTH - _p(16), y + row_h - _p(4)), fill=(18, 40, 60, 210))
        portrait = portraits.get(row.portrait_url)
        text_x = _p(28)
        if portrait is not None:
            _paste(canvas, _circle(portrait, icon), (_p(24), y + _p(4)))
            text_x = _p(64)
        label = character_zh(row.character) if character_zh else row.character
        draw.text(
            (text_x, y + _p(10)),
            _ellipsis(draw, label or "—", name_font, _p(180)),
            font=name_font,
            fill=TEXT,
        )
        bar_x = _p(280)
        bar_y = y + _p(16)
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_w, bar_y + _p(10)),
            radius=_p(5),
            fill=(28, 52, 74, 255),
        )
        if peak > 0:
            fill_w = max(0, min(bar_w, int(bar_w * _share_value(row.share) / peak)))
            if fill_w > 0:
                draw.rounded_rectangle(
                    (bar_x, bar_y, bar_x + fill_w, bar_y + _p(10)),
                    radius=_p(5),
                    fill=GOLD,
                )
        share = row.share or "—"
        draw.text((bar_x + bar_w + _p(12), y + _p(8)), share, font=rate_font, fill=GOLD)
        detail = f"{row.appearances}场 · {row.players}人"
        detail_w = _text_size(draw, detail, small_font)[0]
        draw.text((_WIDTH - _p(28) - detail_w, y + _p(12)), detail, font=small_font, fill=MUTED)
        y += row_h
    _footer(canvas, y + _p(4), updated)
    _finish(canvas, out_path)


_MATRIX_GOOD = ((214, 232, 214, 255), (28, 108, 62, 255))
_MATRIX_BAD = ((244, 214, 214, 255), (164, 48, 58, 255))
_MATRIX_EVEN = ((255, 255, 255, 255), (62, 66, 74, 255))
_MATRIX_PAGE = (244, 240, 232, 255)
_MATRIX_INK = (42, 48, 56, 255)
_MATRIX_CELL = 62
_MATRIX_GAP = 3
_MATRIX_LABEL = 214


def _plain_portrait(image: Image.Image, size: int) -> Image.Image:
    icon = image.convert("RGBA").resize((size, size), Image.Resampling.LANCZOS)
    mask = _aa_disc(size)
    circled = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    circled.paste(icon, (0, 0), mask)
    return circled


def render_matrix(
    matrix,
    out_path: str,
    title: str,
    subtitle: str,
    portraits: dict[str, Image.Image],
    character_zh=None,
    updated: str = "",
) -> None:
    columns = matrix.columns
    count = len(columns)
    cell = _MATRIX_CELL
    gap = _MATRIX_GAP
    label_w = _MATRIX_LABEL
    pad = 28
    title_h = 92
    head_h = cell
    width = pad + label_w + count * (cell + gap) + pad
    height = title_h + head_h + gap + count * (cell + gap) + 48
    canvas = Image.new("RGBA", (width, height), _MATRIX_PAGE)
    draw = ImageDraw.Draw(canvas)
    draw.rectangle((0, 0, 8, height), fill=GOLD)
    title_font = _font(36, _YAHEI_BD, _SEGOE_BD)
    sub_font = _font(20, _YAHEI, _SEGOE)
    name_font = _font(18, _YAHEI, _SEGOE)
    rate_font = _font(16, _YAHEI, _SEGOE)
    draw.text((pad, 22), title, font=title_font, fill=_MATRIX_INK)
    draw.text((pad, 64), subtitle, font=sub_font, fill=(110, 96, 64, 255))

    origin_x = pad + label_w
    origin_y = title_h
    icon = cell - 16
    for index, column in enumerate(columns):
        portrait = portraits.get(column.portrait_url)
        x = origin_x + index * (cell + gap)
        if portrait is not None:
            _paste(
                canvas,
                _plain_portrait(portrait, icon),
                (x + (cell - icon) // 2, origin_y + (head_h - icon) // 2),
            )

    body_y = origin_y + head_h + gap
    for index, (slot, cells) in enumerate(matrix.rows):
        y = body_y + index * (cell + gap)
        portrait = portraits.get(slot.portrait_url)
        if portrait is not None:
            _paste(canvas, _plain_portrait(portrait, icon), (pad, y + (cell - icon) // 2))
        label = character_zh(slot.name) if character_zh else slot.name
        draw.text(
            (pad + icon + 10, y + (cell - 18) // 2),
            _ellipsis(draw, label or "—", name_font, label_w - icon - 16),
            font=name_font,
            fill=_MATRIX_INK,
        )
        for col_index, item in enumerate(cells):
            fill, ink = {
                "good": _MATRIX_GOOD,
                "bad": _MATRIX_BAD,
            }.get(item.tone, _MATRIX_EVEN)
            x = origin_x + col_index * (cell + gap)
            draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=fill)
            rate = item.rate or "—"
            text_w, text_h = _text_size(draw, rate, rate_font)
            draw.text(
                (x + (cell - text_w) / 2, y + (cell - text_h) / 2 - 1),
                rate,
                font=rate_font,
                fill=ink,
            )
    ink = (120, 112, 98, 255)
    if updated:
        draw.text((pad, height - 34), f"数据更新 {updated}", font=sub_font, fill=ink)
        credit = "puddle.farm/gbvsr"
        credit_w = _text_size(draw, credit, sub_font)[0]
        draw.text((width - pad - credit_w, height - 34), credit, font=sub_font, fill=ink)
    else:
        draw.text((pad, height - 34), "puddle.farm/gbvsr", font=sub_font, fill=ink)
    _finish(canvas, out_path)


def _result_color(result: str) -> tuple[int, int, int, int]:
    if result == "win":
        return WIN
    if result == "loss":
        return LOSS
    return TEXT


def _delta_color(delta: str, result: str) -> tuple[int, int, int, int]:
    if not delta or delta == "—":
        return MUTED
    if delta.startswith("+"):
        return WIN
    if delta[:1] in {"-", "−", "–"}:
        return LOSS
    return _result_color(result)


def render_recent(
    rows: list,
    out_path: str,
    title: str,
    subtitle: str,
    portraits: dict[str, Image.Image],
    rank_icons: dict[str, Image.Image],
    sky: Optional[Image.Image] = None,
    character_zh=None,
    rank_zh=None,
    updated: str = "",
) -> None:
    row_h = _p(56)
    height = _p(118) + row_h * max(1, len(rows)) + _p(42)
    canvas = _prepare(_WIDTH, height, sky)
    y = _header(canvas, title, subtitle)
    draw = ImageDraw.Draw(canvas)
    time_font = _font(_p(13), _YAHEI, _SEGOE)
    body_font = _font(_p(15), _YAHEI, _SEGOE)
    small_font = _font(_p(12), _YAHEI, _SEGOE)
    score_font = _font(_p(16), _SEGOE_BD, _YAHEI_BD)
    delta_font = _font(_p(15), _SEGOE_BD, _YAHEI_BD)
    icon = _p(34)
    for index, row in enumerate(rows):
        if index % 2 == 0:
            draw.rectangle((_p(16), y, _WIDTH - _p(16), y + row_h - _p(6)), fill=(18, 40, 60, 210))
        played = (row.played_at or "").split(" ", 1)
        date = played[0] if played and played[0] else "—"
        clock = played[1] if len(played) > 1 else ""
        draw.text((_p(24), y + _p(8)), date, font=time_font, fill=MUTED)
        if clock:
            draw.text((_p(24), y + _p(28)), clock, font=time_font, fill=MUTED)
        portrait = portraits.get(row.portrait_url)
        if portrait is not None:
            _paste(canvas, _circle(portrait, icon), (_p(118), y + _p(8)))
        name_font = font_for(_p(16), row.opponent or "", bold=True)
        name = _ellipsis(draw, row.opponent or "—", name_font, _p(168))
        draw.text((_p(160), y + _p(6)), name, font=name_font, fill=TEXT)
        if row.platform:
            draw.text((_p(160), y + _p(28)), row.platform, font=small_font, fill=MUTED)
        character = character_zh(row.character) if character_zh else row.character
        draw.text(
            (_p(340), y + _p(16)),
            _ellipsis(draw, character or "—", body_font, _p(130)),
            font=body_font,
            fill=TEXT,
        )
        rank_icon = rank_icons.get(row.rank_icon_url)
        rank_x = _p(478)
        if rank_icon is not None:
            _paste(
                canvas,
                rank_icon.convert("RGBA").resize((icon, icon), Image.Resampling.LANCZOS),
                (_p(476), y + _p(8)),
            )
            rank_x = _p(516)
        rank_name = rank_zh(row.rank) if rank_zh else row.rank
        draw.text(
            (rank_x, y + _p(6)),
            _ellipsis(draw, rank_name or "—", body_font, _p(130)),
            font=body_font,
            fill=GOLD,
        )
        points = row.points or ""
        if points and row.unit:
            points = f"{points} {row.unit}"
        if points:
            draw.text((rank_x, y + _p(28)), points, font=small_font, fill=MUTED)
        score = row.score or "—"
        score_color = _result_color(row.result)
        score_w = _text_size(draw, score, score_font)[0]
        draw.text((_p(748) - score_w, y + _p(14)), score, font=score_font, fill=score_color)
        delta = row.delta or "—"
        delta_w = _text_size(draw, delta, delta_font)[0]
        draw.text(
            (_WIDTH - _p(24) - delta_w, y + _p(15)),
            delta,
            font=delta_font,
            fill=_delta_color(delta, row.result),
        )
        y += row_h
    _footer(canvas, y + _p(4), updated)
    _finish(canvas, out_path)
