"""Fetch and parse GBVSR player pages on puddle.farm.

The public /api host is Guilty Gear Strive. GBVSR data is rendered into the
HTML of https://puddle.farm/gbvsr/.
"""

from __future__ import annotations

import asyncio
import html
import importlib.util
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import urljoin

import aiohttp


def _load_names():
    """Load this plugin's names.py by path.

    A bare ``import names`` stays in sys.modules across AstrBot reloads, so
    alias updates never reached the player lookup. The chat reply uses the
    freshly loaded module and would name a character the lookup could not see.
    """
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "names.py")
    full_name = "astrbot_plugin_gbvsr.names"
    spec = importlib.util.spec_from_file_location(full_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载角色名表: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_names = _load_names()
resolve_character = _names.resolve_character
character_id = _names.character_id

logger = logging.getLogger("astrbot_plugin_gbvsr")

BASE_URL = "https://puddle.farm/gbvsr"
SITE_ORIGIN = "https://puddle.farm"
USER_AGENT = "ebifightclub-gbvsr-bot/0.1"

_SEARCH_LINK_RE = re.compile(
    r'<a[^>]*class="player-link"[^>]*href="/gbvsr/player/(\d+)"[^>]*>([^<]*)</a>'
    r'\s*<span class="platform">([^<]*)</span>',
    re.IGNORECASE,
)
_DESC_RE = re.compile(
    r'<meta[^>]*name="description"[^>]*content="([^"]*)"',
    re.IGNORECASE,
)
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_H2_RE = re.compile(
    r"<h2>(.*?)<span class=\"platform\">([^<]*)</span>",
    re.IGNORECASE | re.DOTALL,
)
_ART_RE = re.compile(
    r'class="profile-backdrop"[^>]*src="([^"]+)"',
    re.IGNORECASE,
)
_SKY_RE = re.compile(
    r'<img\b[^>]*class="hero-sky"[^>]*src="([^"]+)"',
    re.IGNORECASE,
)
_SKY_HREF_RE = re.compile(
    r'href="([^"]*\/sky-\d+[^"]*)"',
    re.IGNORECASE,
)
_SEASON_RE = re.compile(r"Season(?:<[^>]+>|\s)+(\d+)", re.IGNORECASE)
_RECORD_RE = re.compile(
    r"<strong>\s*([\d.]+)%\s*</strong>\s*<span>\s*(\d+)W\s*/\s*(\d+)L",
    re.IGNORECASE,
)
_NAV_RE = re.compile(
    r'aria-label="Player characters">(.*?)</nav>',
    re.IGNORECASE | re.DOTALL,
)
_NAV_LINK_RE = re.compile(r"<a\b([^>]*)>(.*?)</a>", re.IGNORECASE | re.DOTALL)
_IMG_RE = re.compile(r"<img\b([^>]*)>", re.IGNORECASE)
_FIELD_RE = re.compile(
    r"Character:\s*(?P<character>[^·]+)\s*·\s*Rank:\s*(?P<rank>[^·]+)"
    r"(?:\s*·\s*Rating:\s*(?P<mp>[\d,]+)\s*(?P<unit>[A-Za-z]+))?"
    r"(?:\s*·\s*Global position:\s*(?P<global>#[\d,]+))?"
    r"(?:\s*·\s*Character position:\s*(?P<character_rank>#[\d,]+))?"
    r"(?:\s*·\s*Matches:\s*(?P<matches>[\d,]+))?",
    re.IGNORECASE,
)


class PuddleError(Exception):
    """Failure the chat can show directly."""


@dataclass
class SearchHit:
    player_id: str
    name: str
    platform: str


@dataclass
class CharacterSlot:
    character_id: str
    name: str
    portrait_url: str
    current: bool = False


@dataclass
class BoardRow:
    position: int
    name: str
    platform: str
    character: str
    rank: str
    mp: str
    portrait_url: str
    rank_icon_url: str


@dataclass
class MatchupRow:
    character: str
    matches: str
    wins: str
    win_rate: str
    portrait_url: str


@dataclass
class RateRow:
    character: str
    win_rate: str
    matches: str
    portrait_url: str


@dataclass
class UsageRow:
    character: str
    share: str
    appearances: str
    players: str
    portrait_url: str


@dataclass
class MatchupReport:
    character: str
    cohort: str
    matchups: list[MatchupRow]
    overall: list[RateRow]
    sky_url: str
    updated: str = ""


@dataclass
class MatrixSlot:
    name: str
    portrait_url: str


@dataclass
class MatrixCell:
    rate: str
    matches: str
    tone: str


@dataclass
class MatchupMatrix:
    columns: list[MatrixSlot]
    rows: list[tuple[MatrixSlot, list[MatrixCell]]]
    cohort: str
    updated: str = ""


@dataclass
class RecentSet:
    played_at: str
    opponent: str
    platform: str
    character: str
    portrait_url: str
    rank: str
    rank_icon_url: str
    points: str
    unit: str
    score: str
    result: str
    delta: str
    partial: bool = False


@dataclass
class PlayerProfile:
    player_id: str
    name: str
    platform: str
    character: str
    character_id: str
    rank: str
    mp: str
    global_rank: str
    character_rank: str
    matches: str
    win_rate: str
    wins: str
    losses: str
    season: str
    art_url: str
    rank_icon_url: str
    sky_url: str
    page_url: str
    updated: str = ""
    rating_unit: str = "MP"
    characters: list[CharacterSlot] = field(default_factory=list)
    recent: list[RecentSet] = field(default_factory=list)
    recent_older_url: str = ""

    @property
    def others(self) -> list[CharacterSlot]:
        return [slot for slot in self.characters if not slot.current]


def absolute_url(path: str) -> str:
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return urljoin(SITE_ORIGIN, path)


def _clean_text(raw: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    return " ".join(text.split())


def _attr(tag_attrs: str, name: str) -> str:
    match = re.search(
        rf'{name}\s*=\s*"([^"]*)"',
        tag_attrs,
        re.IGNORECASE,
    )
    return html.unescape(match.group(1)) if match else ""


def _portrait_url(img_attrs: str) -> str:
    srcset = _attr(img_attrs, "srcset")
    if srcset:
        best = ""
        best_scale = -1.0
        for part in srcset.split(","):
            bits = part.strip().split()
            if not bits:
                continue
            scale = 1.0
            if len(bits) > 1 and bits[1].endswith("x"):
                try:
                    scale = float(bits[1][:-1])
                except ValueError:
                    scale = 1.0
            if scale >= best_scale:
                best_scale = scale
                best = bits[0]
        if best:
            return absolute_url(best)
    return absolute_url(_attr(img_attrs, "src"))


def _format_mp(raw: str) -> str:
    digits = raw.replace(",", "").strip()
    if digits.isdigit():
        return f"{int(digits):,}"
    return raw.strip()


def parse_search(page_html: str) -> list[SearchHit]:
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for player_id, name, platform in _SEARCH_LINK_RE.findall(page_html):
        if player_id in seen:
            continue
        seen.add(player_id)
        hits.append(
            SearchHit(
                player_id=player_id,
                name=_clean_text(name),
                platform=_clean_text(platform),
            )
        )
    return hits


def _parse_characters(page_html: str) -> list[CharacterSlot]:
    nav = _NAV_RE.search(page_html)
    if not nav:
        return []
    slots: list[CharacterSlot] = []
    for attrs, inner in _NAV_LINK_RE.findall(nav.group(1)):
        href = _attr(attrs, "href")
        id_match = re.search(r"[?&]character=(\d+)", html.unescape(href))
        if not id_match:
            continue
        img = _IMG_RE.search(inner)
        portrait = _portrait_url(img.group(1)) if img else ""
        name = _clean_text(inner)
        if not name:
            continue
        slots.append(
            CharacterSlot(
                character_id=id_match.group(1),
                name=name,
                portrait_url=portrait,
                current="aria-current" in attrs.lower(),
            )
        )
    return slots


_CST = timezone(timedelta(hours=8))


def format_updated(raw: str) -> str:
    text = raw.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return ""
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    local = moment.astimezone(_CST)
    return f"{local.month}月{local.day}日 {local.hour:02d}:{local.minute:02d}"


def page_updated(page_html: str, kind: str) -> str:
    if kind == "board":
        pattern = r'class="leaderboard-updated">.*?<time\b[^>]*\bdateTime="([^"]+)"'
    elif kind == "player":
        pattern = r'Snapshot(?:<!--\s*-->)?\s*<time\b[^>]*\bdateTime="([^"]+)"'
    else:
        pattern = r'Updated(?:<!--\s*-->)?\s*<time\b[^>]*\bdateTime="([^"]+)"'
    match = re.search(pattern, page_html, re.IGNORECASE | re.DOTALL)
    return format_updated(match.group(1)) if match else ""


def _sky_url(page_html: str) -> str:
    match = _SKY_RE.search(page_html)
    if match:
        return absolute_url(match.group(1))
    fallback = _SKY_HREF_RE.search(page_html)
    return absolute_url(fallback.group(1)) if fallback else ""


def _rank_icon_url(page_html: str, rank: str) -> str:
    if not rank:
        return ""
    for attrs in _IMG_RE.findall(page_html):
        alt = _attr(attrs, "alt")
        src = _attr(attrs, "src")
        if alt == rank and "rank-" in src:
            return absolute_url(src)
    return ""


_RECENT_SECTION_RE = re.compile(
    r'<section\b[^>]*aria-labelledby="recent-matches-title"[^>]*>(.*?)</section>',
    re.IGNORECASE | re.DOTALL,
)
_MATCH_GROUP_RE = re.compile(
    r'<details\b[^>]*class="[^"]*\bmatch-group\b[^"]*"[^>]*>(.*?)</details>',
    re.IGNORECASE | re.DOTALL,
)
_SCORE_RE = re.compile(
    r'class="match-group-score([^"]*)">(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_DELTA_RE = re.compile(
    r'class="rating-change([^"]*)"[^>]*>(.*?)</span>',
    re.IGNORECASE | re.DOTALL,
)
_POINTS_RE = re.compile(
    r'([\d,]+)\s*(?:<!--.*?-->)?\s*<small class="muted">(MP|RP)</small>',
    re.IGNORECASE | re.DOTALL,
)


def _score_text(raw: str) -> str:
    text = _clean_text(raw)
    return re.sub(r"\s*[–—-]\s*", "–", text)


def _delta_text(raw: str) -> tuple[str, bool]:
    text = _clean_text(raw).replace(" *", "*")
    partial = "partial recorded change" in raw.lower() or text.endswith("*")
    if partial and text and not text.endswith("*"):
        text += "*"
    if not text or text in {"-", "—", "–"}:
        return "—", False
    return text, partial


def _set_result(score_class: str) -> str:
    if "result-loss" in score_class:
        return "loss"
    if "result-win" in score_class:
        return "win"
    return ""


def _fill_templates(fragment: str, blocks: dict[str, str], seen: set[str] | None = None) -> str:
    """Splice streamed Next.js blocks into empty suspense templates.

    Later match pages leave the groups in a hidden block, and the rank,
    time, and point cells inside that block are templates of their own.
    """
    seen = set() if seen is None else seen

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        if key in seen:
            return match.group(0)
        content = blocks.get(f"S:{key}", "")
        if not content or "recent-matches-title" in content:
            return match.group(0)
        seen.add(key)
        if "<template" in content:
            content = _fill_templates(content, blocks, seen)
        return content

    return re.sub(r'<template id="[A-Z]:([^"]*)">\s*</template>', replace, fragment)


def recent_older_url(page_html: str) -> str:
    section = _RECENT_SECTION_RE.search(page_html)
    if not section:
        return ""
    nav = re.search(
        r'<nav\b[^>]*aria-label="Match history pages"[^>]*>(.*?)</nav>',
        section.group(0),
        re.IGNORECASE | re.DOTALL,
    )
    if not nav:
        return ""
    for attrs, text in re.findall(r"<a\b([^>]*)>(.*?)</a>", nav.group(1), re.IGNORECASE | re.DOTALL):
        if "Older" not in _clean_text(text):
            continue
        href = html.unescape(_attr(attrs, "href"))
        return absolute_url(href)
    return ""


def parse_recent_matches(page_html: str) -> list[RecentSet]:
    section = _RECENT_SECTION_RE.search(page_html)
    if not section:
        return []
    fragment = section.group(1)
    if "<template" in fragment:
        fragment = _fill_templates(fragment, _hidden_blocks(page_html))
    sets: list[RecentSet] = []
    for group in _MATCH_GROUP_RE.findall(fragment):
        summary = re.search(r"<summary\b[^>]*>(.*?)</summary>", group, re.IGNORECASE | re.DOTALL)
        fragment = summary.group(1) if summary else group
        when = re.search(r'<time\b[^>]*\bdateTime="([^"]+)"', fragment, re.IGNORECASE)
        name = re.search(r'class="player-link"[^>]*>([^<]*)', fragment, re.IGNORECASE)
        platform = re.search(r'class="platform">([^<]*)', fragment, re.IGNORECASE)
        character = re.search(r"<small>([^<]*)</small>", fragment, re.IGNORECASE)
        rank = re.search(
            r'class="rank-icon-label"\s+title="([^"]+)"',
            fragment,
            re.IGNORECASE,
        )
        rank_icon = ""
        for attrs in _IMG_RE.findall(fragment):
            src = _attr(attrs, "src")
            if "rank-" in src:
                rank_icon = absolute_url(src)
                break
        points = _POINTS_RE.search(fragment)
        score = _SCORE_RE.search(fragment)
        delta = _DELTA_RE.search(fragment)
        opponent = _clean_text(name.group(1)) if name else ""
        score_text = _score_text(score.group(2)) if score else ""
        if not opponent and not score_text:
            continue
        delta_text, partial = _delta_text(delta.group(2) if delta else "")
        sets.append(
            RecentSet(
                played_at=format_updated(when.group(1)) if when else "",
                opponent=opponent,
                platform=_clean_text(platform.group(1)) if platform else "",
                character=_clean_text(character.group(1)) if character else "",
                portrait_url=_row_portrait(fragment),
                rank=html.unescape(rank.group(1)) if rank else "",
                rank_icon_url=rank_icon,
                points=_format_mp(points.group(1)) if points else "",
                unit=points.group(2).upper() if points else "",
                score=score_text,
                result=_set_result(score.group(1) if score else ""),
                delta=delta_text,
                partial=partial,
            )
        )
    return sets


def parse_player(page_html: str, player_id: str) -> PlayerProfile:
    desc_match = _DESC_RE.search(page_html)
    description = html.unescape(desc_match.group(1)) if desc_match else ""
    fields = _FIELD_RE.search(description)
    if not fields:
        if description and "Character:" not in description:
            raise PuddleError("没有找到这个玩家。")
        raise PuddleError("这个玩家页暂时解析不了。")

    h2 = _H2_RE.search(page_html)
    if h2:
        name = _clean_text(h2.group(1))
        platform = _clean_text(h2.group(2))
    else:
        title = _TITLE_RE.search(page_html)
        title_text = _clean_text(title.group(1)) if title else ""
        name = title_text.split("·")[0].strip() if title_text else ""
        platform = ""
    if not name:
        raise PuddleError("这个玩家页暂时解析不了。")

    characters = _parse_characters(page_html)
    current = next((slot for slot in characters if slot.current), None)
    if current is None and characters:
        current = characters[0]
        current.current = True
    character_id = current.character_id if current else ""
    if current and current.name:
        character_name = current.name
    else:
        character_name = fields.group("character").strip()

    record = _RECORD_RE.search(page_html)
    season_match = _SEASON_RE.search(page_html)
    art_match = _ART_RE.search(page_html)
    rank = fields.group("rank").strip()
    raw_mp = fields.group("mp")
    rating_unit = (fields.group("unit") or "").upper()
    page_url = f"{BASE_URL}/player/{player_id}"
    if character_id:
        page_url = f"{page_url}?character={character_id}"

    return PlayerProfile(
        player_id=player_id,
        name=name,
        platform=platform,
        character=character_name,
        character_id=character_id,
        rank=rank,
        mp=_format_mp(raw_mp) if raw_mp else "—",
        rating_unit=rating_unit,
        global_rank=(fields.group("global") or "—").strip(),
        character_rank=(fields.group("character_rank") or "—").strip(),
        matches=(fields.group("matches") or "").replace(",", "").strip(),
        win_rate=f"{record.group(1)}%" if record else "—",
        wins=record.group(2) if record else "",
        losses=record.group(3) if record else "",
        season=season_match.group(1) if season_match else "",
        art_url=absolute_url(art_match.group(1)) if art_match else "",
        rank_icon_url=_rank_icon_url(page_html, rank),
        sky_url=_sky_url(page_html),
        page_url=page_url,
        updated=page_updated(page_html, "player"),
        characters=characters,
        recent=parse_recent_matches(page_html),
        recent_older_url=recent_older_url(page_html),
    )


def _select_block(page_html: str, name: str) -> str:
    match = re.search(
        rf'<select\b[^>]*name="{name}"[^>]*>(.*?)</select>',
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    return match.group(1) if match else ""


def listed_seasons(page_html: str) -> list[str]:
    return re.findall(r'value="(\d+)"', _select_block(page_html, "season"))


def selected_season(page_html: str) -> str:
    match = re.search(
        r'value="(\d+)"[^>]*selected',
        _select_block(page_html, "season"),
        re.IGNORECASE,
    )
    return match.group(1) if match else ""


def selected_cohort(page_html: str) -> str:
    match = re.search(
        r'value="([^"]*)"[^>]*selected',
        _select_block(page_html, "cohort"),
        re.IGNORECASE,
    )
    return (match.group(1) if match else "") or "all"


def _row_portrait(row_html: str) -> str:
    match = re.search(r'<img\b([^>]*class="portrait"[^>]*)>', row_html, re.IGNORECASE)
    if not match:
        return ""
    return _portrait_url(match.group(1))


def _row_character(row_html: str) -> str:
    match = re.search(
        r'class="character-name">.*?<span>([^<]+)</span>',
        row_html,
        re.IGNORECASE | re.DOTALL,
    )
    return _clean_text(match.group(1)) if match else ""


def _row_numbers(row_html: str, character: str) -> list[str]:
    cells = [
        _clean_text(cell)
        for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.IGNORECASE | re.DOTALL)
    ]
    return [cell for cell in cells if cell and cell != character]


def _hidden_blocks(page_html: str) -> dict[str, str]:
    """Map Next.js suspense ids (S:…) to the HTML streamed after the first rows."""
    blocks: dict[str, str] = {}
    for match in re.finditer(r'<div hidden id="(S:[^"]+)">', page_html):
        start = match.end()
        depth = 1
        index = start
        while index < len(page_html) and depth:
            next_open = page_html.find("<div", index)
            next_close = page_html.find("</div>", index)
            if next_close < 0:
                break
            if 0 <= next_open < next_close:
                depth += 1
                index = next_open + 4
            else:
                depth -= 1
                if depth == 0:
                    blocks[match.group(1)] = page_html[start:next_close]
                    break
                index = next_close + 6
    return blocks


def _inline_templates(page_html: str) -> str:
    blocks = _hidden_blocks(page_html)
    if not blocks:
        return page_html

    def replace(match: re.Match[str]) -> str:
        content = blocks.get(f"S:{match.group(1)}", "")
        # The first suspense block wraps the whole page. Inlining it would
        # copy the table, including the still-empty placeholders.
        if not content or "<tr" in content or "<template" in content:
            return match.group(0)
        return content

    return re.sub(r'<template id="[A-Z]:([^"]*)"></template>', replace, page_html)


def parse_leaderboard(page_html: str) -> list[BoardRow]:
    page_html = _inline_templates(page_html)
    rows: list[BoardRow] = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", page_html, re.IGNORECASE | re.DOTALL):
        position = re.search(r'class="position">(\d+)<', row_html)
        link = re.search(
            r'class="player-link"[^>]*>([^<]*)</a>',
            row_html,
            re.IGNORECASE,
        )
        if not position or not link:
            continue
        platform = re.search(r'class="platform">([^<]*)</span>', row_html, re.IGNORECASE)
        rank = ""
        rank_icon = ""
        for attrs in _IMG_RE.findall(row_html):
            src = _attr(attrs, "src")
            if "rank-" in src:
                rank_icon = absolute_url(src)
                rank = _attr(attrs, "alt")
                break
        points = re.search(r'title="Master points">\s*([\d,]+)', row_html, re.IGNORECASE)
        rows.append(
            BoardRow(
                position=int(position.group(1)),
                name=_clean_text(link.group(1)),
                platform=_clean_text(platform.group(1)) if platform else "",
                character=_row_character(row_html),
                rank=rank,
                mp=points.group(1) if points else "—",
                portrait_url=_row_portrait(row_html),
                rank_icon_url=rank_icon,
            )
        )
    return rows


def parse_popularity(page_html: str) -> list[UsageRow]:
    table = re.search(r"<table\b[^>]*>(.*?)</table>", page_html, re.IGNORECASE | re.DOTALL)
    if not table:
        raise PuddleError("角色使用率暂时解析不了。")
    rows: list[UsageRow] = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table.group(1), re.IGNORECASE | re.DOTALL):
        name = _row_character(row_html)
        cells = [
            _clean_text(cell)
            for cell in re.findall(r"<td\b[^>]*>(.*?)</td>", row_html, re.IGNORECASE | re.DOTALL)
        ]
        cells = [cell for cell in cells if cell and cell != name]
        if not name or len(cells) < 3:
            continue
        rows.append(
            UsageRow(
                character=name,
                share=cells[0],
                appearances=cells[1],
                players=cells[2],
                portrait_url=_row_portrait(row_html),
            )
        )
    if not rows:
        raise PuddleError("角色使用率暂时解析不了。")
    return rows


def parse_overall_rates(page_html: str) -> list[RateRow]:
    table = re.search(
        r'<table\b[^>]*aria-label="Characters ranked by overall win rate"[^>]*>(.*?)</table>',
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    if not table:
        raise PuddleError("总体胜率暂时解析不了。")
    rows: list[RateRow] = []
    for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table.group(1), re.IGNORECASE | re.DOTALL):
        name = _row_character(row_html)
        numbers = _row_numbers(row_html, name)
        if not name or len(numbers) < 2:
            continue
        rows.append(
            RateRow(
                character=name,
                win_rate=numbers[0],
                matches=numbers[1],
                portrait_url=_row_portrait(row_html),
            )
        )
    if not rows:
        raise PuddleError("总体胜率暂时解析不了。")
    return rows


def parse_matchup_page(page_html: str) -> MatchupReport:
    matchups: list[MatchupRow] = []
    overall: list[RateRow] = []
    character = ""
    parts = re.split(r"<h2\b[^>]*>", page_html, flags=re.IGNORECASE)
    for part in parts[1:]:
        title_match = re.match(r"(.*?)</h2>(.*)", part, re.IGNORECASE | re.DOTALL)
        if not title_match:
            continue
        title = _clean_text(title_match.group(1))
        body = title_match.group(2)
        folded = title.casefold()
        if folded.endswith("matchups"):
            character = re.sub(r"'s matchups$", "", title, flags=re.IGNORECASE).strip()
            for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.IGNORECASE | re.DOTALL):
                name = _row_character(row_html)
                numbers = _row_numbers(row_html, name)
                if not name or len(numbers) < 3:
                    continue
                matchups.append(
                    MatchupRow(
                        character=name,
                        matches=numbers[0],
                        wins=numbers[1],
                        win_rate=numbers[2],
                        portrait_url=_row_portrait(row_html),
                    )
                )
        elif "win rate" in folded:
            for row_html in re.findall(r"<tr\b[^>]*>(.*?)</tr>", body, re.IGNORECASE | re.DOTALL):
                name = _row_character(row_html)
                numbers = _row_numbers(row_html, name)
                if not name or len(numbers) < 2:
                    continue
                overall.append(
                    RateRow(
                        character=name,
                        win_rate=numbers[0],
                        matches=numbers[1],
                        portrait_url=_row_portrait(row_html),
                    )
                )
    return MatchupReport(
        character=character,
        cohort=selected_cohort(page_html),
        matchups=matchups,
        overall=overall,
        sky_url=_sky_url(page_html),
        updated=page_updated(page_html, "rates"),
    )


_CELL_TITLE_RE = re.compile(
    r":\s*([\d.]+%)\s*,\s*([\d,]+)\s+matches",
    re.IGNORECASE,
)


def _matrix_slot(attrs: str, inner: str) -> MatrixSlot:
    img = _IMG_RE.search(inner)
    name = _attr(attrs, "title") or _clean_text(inner)
    return MatrixSlot(
        name=name,
        portrait_url=_portrait_url(img.group(1)) if img else "",
    )


def _matrix_cell(attrs: str, inner: str) -> MatrixCell:
    title = _attr(attrs, "title")
    parsed = _CELL_TITLE_RE.search(title)
    rate = parsed.group(1) if parsed else _clean_text(inner)
    matches = parsed.group(2) if parsed else ""
    klass = set(_attr(attrs, "class").split())
    if "good" in klass:
        tone = "good"
    elif "bad" in klass:
        tone = "bad"
    else:
        tone = "even"
    return MatrixCell(rate=rate, matches=matches, tone=tone)


def parse_matchup_matrix(page_html: str) -> MatchupMatrix:
    table = re.search(
        r'<table\b[^>]*class="matrix"[^>]*>(.*?)</table>',
        page_html,
        re.IGNORECASE | re.DOTALL,
    )
    if not table:
        raise PuddleError("角色对位表暂时解析不了。")
    row_html = re.findall(r"<tr\b[^>]*>(.*?)</tr>", table.group(1), re.IGNORECASE | re.DOTALL)
    if len(row_html) < 2:
        raise PuddleError("角色对位表暂时解析不了。")

    columns: list[MatrixSlot] = []
    for attrs, inner in re.findall(r"<th\b([^>]*)>(.*?)</th>", row_html[0], re.IGNORECASE | re.DOTALL):
        if "col" not in _attr(attrs, "scope"):
            continue
        columns.append(_matrix_slot(attrs, inner))

    rows: list[tuple[MatrixSlot, list[MatrixCell]]] = []
    for raw in row_html[1:]:
        head = re.search(r"<th\b([^>]*)>(.*?)</th>", raw, re.IGNORECASE | re.DOTALL)
        if not head:
            continue
        cells = [
            _matrix_cell(attrs, inner)
            for attrs, inner in re.findall(r"<td\b([^>]*)>(.*?)</td>", raw, re.IGNORECASE | re.DOTALL)
        ]
        if len(cells) != len(columns):
            continue
        rows.append((_matrix_slot(head.group(1), head.group(2)), cells))
    if not columns or len(rows) != len(columns):
        raise PuddleError("角色对位表暂时解析不了。")
    return MatchupMatrix(
        columns=columns,
        rows=rows,
        cohort=selected_cohort(page_html),
        updated=page_updated(page_html, "rates"),
    )


def pick_character(slots: list[CharacterSlot], query: str) -> Optional[CharacterSlot]:
    needle = " ".join(query.split()).casefold()
    if not needle:
        return None
    english = resolve_character(query)
    if english:
        target = english.casefold()
        target_id = character_id(query)
        for slot in slots:
            if target_id and slot.character_id == target_id:
                return slot
            if slot.name.casefold() == target or resolve_character(slot.name) == english:
                return slot
        return None
    exact = [slot for slot in slots if slot.name.casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        return exact[0]
    partial = [slot for slot in slots if needle in slot.name.casefold()]
    if len(partial) == 1:
        return partial[0]
    return None


class PuddleClient:
    def __init__(self, timeout_sec: int = 20) -> None:
        self.timeout_sec = max(5, int(timeout_sec))

    def _timeout(self) -> aiohttp.ClientTimeout:
        return aiohttp.ClientTimeout(total=self.timeout_sec)

    async def _text(self, session: aiohttp.ClientSession, url: str) -> str:
        async with session.get(url) as resp:
            if resp.status == 404:
                raise PuddleError("没有找到这个玩家。")
            if resp.status >= 400:
                raise PuddleError(f"puddle.farm 返回了 {resp.status}。")
            return await resp.text()

    async def search(self, query: str) -> list[SearchHit]:
        url = f"{BASE_URL}/search"
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout(),
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            ) as session:
                async with session.get(url, params={"q": query}) as resp:
                    if resp.status >= 400:
                        raise PuddleError(f"搜索失败（{resp.status}）。")
                    page = await resp.text()
        except PuddleError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("搜索请求失败: %s", exc)
            raise PuddleError("暂时连不上 puddle.farm。") from exc
        return parse_search(page)

    async def player(self, player_id: str, character_id: str = "") -> PlayerProfile:
        if not re.fullmatch(r"\d{6,}", player_id):
            raise PuddleError("玩家 ID 格式不对。")
        url = f"{BASE_URL}/player/{player_id}"
        if character_id:
            if not re.fullmatch(r"\d{1,4}", character_id):
                raise PuddleError("角色参数不对。")
            url = f"{url}?character={character_id}"
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout(),
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            ) as session:
                page = await self._text(session, url)
        except PuddleError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("玩家页请求失败 %s: %s", url, exc)
            raise PuddleError("暂时连不上 puddle.farm。") from exc
        try:
            return parse_player(page, player_id)
        except PuddleError:
            logger.warning("玩家页解析失败: %s", url)
            raise

    async def older_recent(self, url: str) -> tuple[list[RecentSet], str]:
        page = await self._get_html(url)
        return parse_recent_matches(page), recent_older_url(page)

    async def read_bytes(self, urls: list[str]) -> list[Optional[bytes]]:
        if not urls:
            return []

        async def _one(session: aiohttp.ClientSession, url: str) -> Optional[bytes]:
            if not url:
                return None
            try:
                async with session.get(url) as resp:
                    if resp.status != 200:
                        return None
                    return await resp.read()
            except (aiohttp.ClientError, TimeoutError):
                logger.info("图片下载失败: %s", url)
                return None

        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout(),
                headers={"User-Agent": USER_AGENT, "Accept": "image/webp,image/*"},
            ) as session:
                return list(await asyncio.gather(*(_one(session, url) for url in urls)))
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("图片会话失败: %s", exc)
            return [None] * len(urls)

    async def _get_html(self, url: str, params: Optional[dict[str, str]] = None) -> str:
        try:
            async with aiohttp.ClientSession(
                timeout=self._timeout(),
                headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
            ) as session:
                async with session.get(url, params=params or None) as resp:
                    if resp.status >= 400:
                        raise PuddleError(f"puddle.farm 返回了 {resp.status}。")
                    return await resp.text()
        except PuddleError:
            raise
        except (aiohttp.ClientError, TimeoutError) as exc:
            logger.warning("页面请求失败 %s: %s", url, exc)
            raise PuddleError("暂时连不上 puddle.farm。") from exc

    async def leaderboard(
        self, character_id: str = "", season: str = ""
    ) -> tuple[list[BoardRow], str, str]:
        params: dict[str, str] = {}
        if character_id:
            params["character"] = character_id
        if season:
            params["season"] = season
        page = await self._get_html(f"{BASE_URL}/", params)
        seasons = listed_seasons(page)
        if season and seasons and season not in seasons:
            shown = "、".join(f"第{item}赛季" for item in seasons)
            raise PuddleError(f"没有第{season}赛季的排行榜。现有：{shown}。")
        return (
            parse_leaderboard(page),
            selected_season(page) or season,
            _sky_url(page),
            page_updated(page, "board"),
        )

    async def matchups(self, character_id: str, cohort: str = "all") -> MatchupReport:
        if cohort not in {"all", "master"}:
            cohort = "all"
        page = await self._get_html(
            f"{BASE_URL}/matchups",
            {"character": character_id, "cohort": cohort},
        )
        report = parse_matchup_page(page)
        if not report.matchups and not report.overall:
            raise PuddleError("角色胜率暂时解析不了。")
        return report

    async def popularity(self) -> tuple[list[UsageRow], str]:
        page = await self._get_html(f"{BASE_URL}/popularity")
        return parse_popularity(page), _sky_url(page), page_updated(page, "rates")

    async def overall_rates(self, cohort: str = "all") -> tuple[list[RateRow], str, str]:
        if cohort not in {"all", "master"}:
            cohort = "all"
        page = await self._get_html(f"{BASE_URL}/matchups", {"cohort": cohort})
        return (
            parse_overall_rates(page),
            selected_cohort(page) or cohort,
            _sky_url(page),
            page_updated(page, "rates"),
        )

    async def matchup_matrix(self, cohort: str = "all") -> MatchupMatrix:
        if cohort not in {"all", "master"}:
            cohort = "all"
        page = await self._get_html(f"{BASE_URL}/matchups", {"cohort": cohort})
        return parse_matchup_matrix(page)
