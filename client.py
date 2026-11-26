"""Fetch and parse GBVSR player pages on puddle.farm.

The public /api host is Guilty Gear Strive. GBVSR data is rendered into the
HTML of https://puddle.farm/gbvsr/.
"""

from __future__ import annotations

import asyncio
import html
import logging
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urljoin

import aiohttp

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)

from names import resolve_character

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
    r"Character:\s*(?P<character>.*?)\s*·\s*Rank:\s*(?P<rank>.*?)\s*·\s*"
    r"Rating:\s*(?P<mp>[\d,]+)\s*MP"
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
    characters: list[CharacterSlot] = field(default_factory=list)

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


def parse_player(page_html: str, player_id: str) -> PlayerProfile:
    desc_match = _DESC_RE.search(page_html)
    description = html.unescape(desc_match.group(1)) if desc_match else ""
    fields = _FIELD_RE.search(description)
    if not fields:
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
        mp=_format_mp(fields.group("mp")),
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
        characters=characters,
    )


def pick_character(slots: list[CharacterSlot], query: str) -> Optional[CharacterSlot]:
    needle = " ".join(query.split()).casefold()
    if not needle:
        return None
    english = resolve_character(query)
    if english:
        target = english.casefold()
        for slot in slots:
            if slot.name.casefold() == target:
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
