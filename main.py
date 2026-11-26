"""AstrBot 插件：查询 puddle.farm 上的 GBVSR 玩家段位并发送资料卡。

指令统一以 gbvsr 开头，priority=15。
AstrBot 里数字更大的处理器先执行：TOP8 是 20，startggbot 是 10。
本插件只在命中自己的指令时 stop_event，避免抢走「查询」「帮助」「TOP8」。
群里未识别的 @ 会由 startggbot 回复「未知指令」，所以本插件必须排在它前面。
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.util
import json
import logging
import os
import re
import sys
import time
from typing import Any, Optional

import astrbot.api.message_components as Comp
from astrbot.api import AstrBotConfig
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

logger = logging.getLogger("astrbot_plugin_gbvsr")

PLUGIN_NAME = "astrbot_plugin_gbvsr"
_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
LEGACY_DATA_DIR = os.path.join(_PLUGIN_DIR, "data")

# 长指令在前，避免 gbvsr 吃掉 gbvsr帮助 / gbvsr绑定。
COMMANDS = (
    "gbvsr帮助",
    "gbvsr绑定",
    "gbvsr解绑",
    "gbvsr排行榜",
    "gbvsr排行",
    "gbvsr胜率",
    "gbvsr",
)
_BOARD_LIMIT = 50
_SEASON_RE = re.compile(r"^(?:第)?(\d+)赛季$|^赛季(\d+)$|^season(\d+)$", re.IGNORECASE)
_PLAYER_QUERY_RE = re.compile(r"^(\d{10,})(?:\s+(.+))?$")

if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)


def _load_local_module(module_name: str):
    module_path = os.path.join(_PLUGIN_DIR, f"{module_name}.py")
    if not os.path.isfile(module_path):
        raise ImportError(f"缺少插件模块文件: {module_path}")
    full_name = f"astrbot_plugin_gbvsr.{module_name}"
    spec = importlib.util.spec_from_file_location(full_name, module_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载插件模块: {module_name}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[full_name] = module
    spec.loader.exec_module(module)
    return module


_client = _load_local_module("client")
_card = _load_local_module("card")
_names = _load_local_module("names")
_board = _load_local_module("board")

PuddleClient = _client.PuddleClient
PuddleError = _client.PuddleError
PlayerProfile = _client.PlayerProfile
SearchHit = _client.SearchHit
pick_character = _client.pick_character
character_zh = _names.character_zh
rank_zh = _names.rank_zh
resolve_character = _names.resolve_character
character_id = _names.character_id
CardData = _card.CardData
open_image = _card.open_image
render_card = _card.render_card
render_leaderboard = _board.render_leaderboard
render_rates = _board.render_rates
render_matrix = _board.render_matrix


def _ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def _resolve_plugin_data_dir() -> str:
    persistent_dir = LEGACY_DATA_DIR
    try:
        from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

        persistent_dir = os.path.join(get_astrbot_plugin_data_path(), PLUGIN_NAME)
    except ImportError:
        try:
            from astrbot.core.utils.astrbot_path import get_astrbot_data_path

            persistent_dir = os.path.join(
                get_astrbot_data_path(), "plugin_data", PLUGIN_NAME
            )
        except ImportError:
            logger.warning("无法获取 AstrBot plugin_data 路径，回退到插件目录 data/。")
    _ensure_dir(persistent_dir)
    return persistent_dir


def _read_json(path: str, default: Any) -> Any:
    if not os.path.isfile(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        logger.warning("读取 JSON 失败: %s", path)
        return default


def _write_json(path: str, payload: Any) -> None:
    _ensure_dir(os.path.dirname(path))
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)


def _choose_exact(hits: list[SearchHit], query: str) -> Optional[SearchHit]:
    needle = " ".join(query.split())
    exact = [hit for hit in hits if hit.name == needle]
    if len(exact) == 1:
        return exact[0]
    folded = [hit for hit in hits if hit.name.casefold() == needle.casefold()]
    if len(folded) == 1:
        return folded[0]
    return None


_CARD_KEEP = 30
_CLEANUP_INTERVAL_SEC = 6 * 3600
_IMAGE_SUFFIXES = {".webp", ".png", ".jpg", ".jpeg", ".img"}


def _cleanup_files(
    cache_dir: str,
    max_age_sec: int,
    keep_latest: int = 0,
    suffixes: Optional[set[str]] = None,
) -> int:
    try:
        entries = []
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            if not os.path.isfile(path):
                continue
            if suffixes is not None and os.path.splitext(name)[1].lower() not in suffixes:
                continue
            entries.append((os.path.getmtime(path), path))
    except OSError:
        return 0
    entries.sort(reverse=True)
    now = time.time()
    removed = 0
    for index, (mtime, path) in enumerate(entries):
        expired = max_age_sec >= 0 and now - mtime > max_age_sec
        overflow = keep_latest > 0 and index >= keep_latest
        if not expired and not overflow:
            continue
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


@register(
    "astrbot_plugin_gbvsr",
    "Butterfly0v0",
    "查询 puddle.farm 上的 GBVSR 玩家段位",
    "0.2.2",
)
class GbvsrRankPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig = None):
        super().__init__(context)
        self.context = context
        self.config = config or AstrBotConfig({})
        self.data_dir = _resolve_plugin_data_dir()
        self.bindings_path = os.path.join(self.data_dir, "bindings.json")
        self.image_dir = os.path.join(self.data_dir, "images")
        self.card_dir = os.path.join(self.data_dir, "cards")
        _ensure_dir(self.image_dir)
        _ensure_dir(self.card_dir)
        self._cache: dict[str, tuple[float, Any]] = {}
        self._last_query: dict[str, float] = {}
        self._cleanup_task: Optional[asyncio.Task] = None
        self._reload_settings()

    async def initialize(self) -> None:
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def terminate(self) -> None:
        task = self._cleanup_task
        self._cleanup_task = None
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _cleanup_loop(self) -> None:
        try:
            while True:
                try:
                    await asyncio.to_thread(self._sweep_temp_files)
                except Exception:
                    logger.exception("清理临时文件失败")
                await asyncio.sleep(_CLEANUP_INTERVAL_SEC)
        except asyncio.CancelledError:
            return

    def _cfg_int(self, key: str, default: int) -> int:
        if not self.config:
            return default
        try:
            value = self.config.get(key)
        except Exception:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def _reload_settings(self) -> None:
        self.timeout_sec = max(5, self._cfg_int("request_timeout_sec", 20))
        self.cache_sec = max(0, self._cfg_int("cache_sec", 60))
        self.cooldown_sec = max(0, self._cfg_int("cooldown_sec", 5))
        self.max_results = max(1, self._cfg_int("max_results", 5))
        self.card_keep_sec = max(1, self._cfg_int("card_keep_hours", 24)) * 3600
        self.image_keep_sec = max(1, self._cfg_int("image_keep_days", 7)) * 86400
        self.client = PuddleClient(self.timeout_sec)

    def _sweep_temp_files(self) -> None:
        removed_cards = _cleanup_files(
            self.card_dir,
            max_age_sec=self.card_keep_sec,
            keep_latest=_CARD_KEEP,
            suffixes={".png"},
        )
        removed_images = _cleanup_files(
            self.image_dir,
            max_age_sec=self.image_keep_sec,
            suffixes=_IMAGE_SUFFIXES,
        )
        if removed_cards or removed_images:
            logger.info(
                "已清理临时文件：资料卡 %s 张，缓存图 %s 张",
                removed_cards,
                removed_images,
            )

    def _cache_get(self, key: str) -> Any:
        item = self._cache.get(key)
        if not item:
            return None
        stored_at, value = item
        if self.cache_sec and time.monotonic() - stored_at > self.cache_sec:
            self._cache.pop(key, None)
            return None
        return value

    def _cache_set(self, key: str, value: Any) -> None:
        self._cache[key] = (time.monotonic(), value)
        if len(self._cache) > 300:
            oldest = sorted(self._cache.items(), key=lambda item: item[1][0])[:100]
            for old_key, _ in oldest:
                self._cache.pop(old_key, None)

    def _load_bindings(self) -> dict[str, Any]:
        data = _read_json(self.bindings_path, {})
        return data if isinstance(data, dict) else {}

    def _sender_id(self, event: AstrMessageEvent) -> str:
        for attr in ("get_sender_id", "sender_id", "user_id"):
            value = getattr(event, attr, None)
            if callable(value):
                try:
                    return str(value())
                except Exception:
                    continue
            if value is not None:
                return str(value)
        sender = getattr(event, "sender", None)
        if sender:
            uid = getattr(sender, "user_id", None) or getattr(sender, "id", None)
            if uid is not None:
                return str(uid)
        return ""

    def _is_group_message(self, event: AstrMessageEvent) -> bool:
        try:
            return bool(event.get_group_id())
        except Exception:
            msg_type = str(getattr(event, "get_message_type", lambda: "")() or "")
            return "group" in msg_type.lower()

    def _bot_self_id(self, event: AstrMessageEvent) -> str:
        getter = getattr(event, "get_self_id", None)
        if callable(getter):
            try:
                value = getter()
                if value:
                    return str(value)
            except Exception:
                pass
        return str(getattr(event, "self_id", "") or "")

    def _is_at_bot(self, event: AstrMessageEvent) -> bool:
        self_id = self._bot_self_id(event)
        if not self_id:
            return False
        message_obj = getattr(event, "message_obj", None)
        chain = getattr(message_obj, "message", None) if message_obj else None
        if not chain:
            return False
        for seg in chain:
            if isinstance(seg, Comp.At):
                at_id = str(
                    getattr(seg, "qq", "")
                    or getattr(seg, "id", "")
                    or getattr(seg, "user_id", "")
                    or ""
                )
                if at_id == self_id:
                    return True
        return False

    def _extract_command_text(self, event: AstrMessageEvent) -> str:
        text = (getattr(event, "message_str", None) or "").strip()
        if text.startswith("/"):
            text = text.lstrip("/").strip()
        text = re.sub(r"^@\S+\s*", "", text)
        return text.strip()

    def _match_command(self, text: str) -> tuple[Optional[str], str]:
        folded = text.casefold()
        for cmd in COMMANDS:
            if not folded.startswith(cmd):
                continue
            rest = text[len(cmd) :].strip()
            return cmd, rest
        return None, ""

    def _should_handle(self, event: AstrMessageEvent) -> bool:
        text = self._extract_command_text(event)
        cmd, _ = self._match_command(text)
        if cmd is None:
            return False
        if self._is_group_message(event):
            return self._is_at_bot(event)
        return True

    def _cooling_down(self, event: AstrMessageEvent) -> bool:
        if self.cooldown_sec <= 0:
            return False
        sender = self._sender_id(event)
        if not sender:
            return False
        last = self._last_query.get(sender, 0.0)
        return time.monotonic() - last < self.cooldown_sec

    def _mark_query(self, event: AstrMessageEvent) -> None:
        sender = self._sender_id(event)
        if sender:
            self._last_query[sender] = time.monotonic()

    async def _search(self, query: str) -> list[SearchHit]:
        key = f"search:{query.casefold()}"
        cached = self._cache_get(key)
        if cached is not None:
            return cached
        hits = await self.client.search(query)
        self._cache_set(key, hits)
        return hits

    async def _profile(self, player_id: str, character_id: str = "") -> PlayerProfile:
        key = f"player:{player_id}:{character_id or '-'}"
        cached = self._cache_get(key)
        if isinstance(cached, PlayerProfile):
            return cached
        profile = await self.client.player(player_id, character_id)
        self._cache_set(key, profile)
        return profile

    def _image_path(self, url: str) -> str:
        digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
        suffix = os.path.splitext(url.split("?", 1)[0])[1].lower()
        if suffix not in {".webp", ".png", ".jpg", ".jpeg"}:
            suffix = ".img"
        return os.path.join(self.image_dir, f"{digest}{suffix}")

    def _read_cached_image(self, path: str) -> Optional[Any]:
        if not os.path.isfile(path) or os.path.getsize(path) <= 32:
            return None
        try:
            with open(path, "rb") as handle:
                image = open_image(handle.read())
            try:
                os.utime(path, None)
            except OSError:
                pass
            return image
        except Exception:
            logger.info("缓存图片损坏: %s", path)
            return None

    async def _load_images(self, urls: list[str]) -> list[Optional[Any]]:
        images: list[Optional[Any]] = [None] * len(urls)
        missing: list[tuple[int, str, str]] = []
        for index, url in enumerate(urls):
            if not url:
                continue
            path = self._image_path(url)
            cached = self._read_cached_image(path)
            if cached is not None:
                images[index] = cached
                continue
            missing.append((index, url, path))
        if not missing:
            return images
        blobs = await self.client.read_bytes([url for _, url, _ in missing])
        for (index, url, path), blob in zip(missing, blobs):
            if not blob:
                continue
            try:
                images[index] = open_image(blob)
            except Exception:
                logger.info("图片无法解码: %s", url)
                continue
            try:
                with open(path, "wb") as handle:
                    handle.write(blob)
            except OSError:
                pass
        return images

    async def _build_card(self, profile: PlayerProfile) -> str:
        alts = profile.others[:16]
        urls = [profile.art_url, profile.rank_icon_url, profile.sky_url]
        urls.extend(slot.portrait_url for slot in alts)
        images = await self._load_images(urls)
        art = images[0] if images else None
        rank_icon = images[1] if len(images) > 1 else None
        sky = images[2] if len(images) > 2 else None
        alt_images = [image for image in images[3:] if image is not None]
        out_path = os.path.join(
            self.card_dir,
            f"{profile.player_id}_{profile.character_id or 'main'}_{int(time.time() * 1000)}.png",
        )
        card = CardData(
            name=profile.name,
            platform=profile.platform,
            rank=rank_zh(profile.rank),
            character=character_zh(profile.character),
            mp=profile.mp,
            unit=profile.rating_unit,
            global_rank=profile.global_rank,
            character_rank=profile.character_rank,
            win_rate=profile.win_rate,
            wins=profile.wins,
            losses=profile.losses,
            matches=profile.matches,
            season=profile.season,
            art=art,
            rank_icon=rank_icon,
            sky=sky,
            alts=alt_images,
        )
        await asyncio.to_thread(render_card, card, out_path)
        self._sweep_temp_files()
        return out_path

    def _hits_text(self, hits: list[SearchHit]) -> str:
        shown = hits[: self.max_results]
        lines = ["找到多名玩家，请用 ID 再查一次："]
        for hit in shown:
            platform = f" · {hit.platform}" if hit.platform else ""
            lines.append(f"· {hit.name}{platform} · {hit.player_id}")
        hidden = len(hits) - len(shown)
        if hidden > 0:
            lines.append(f"还有 {hidden} 个，把名字写得更完整一些。")
        if shown:
            lines.append(f"示例：gbvsr {shown[0].player_id}")
        return "\n".join(lines)

    async def _resolve_query(self, query: str) -> tuple[Optional[PlayerProfile], str]:
        query = " ".join(query.split())
        if not query:
            return None, "请发送玩家名或 ID。\n示例：gbvsr 言松十文"
        if len(query) > 80:
            return None, "名字太长了。"

        id_match = _PLAYER_QUERY_RE.fullmatch(query)
        if id_match:
            return await self._load_with_character(id_match.group(1), id_match.group(2) or "")

        hits = await self._search(query)
        chosen = _choose_exact(hits, query)
        if chosen:
            return await self._load_with_character(chosen.player_id, "")

        parts = query.split()
        if len(parts) >= 2:
            for size in (2, 1):
                if len(parts) <= size:
                    continue
                name = " ".join(parts[:-size])
                character = " ".join(parts[-size:])
                name_hits = await self._search(name)
                picked = _choose_exact(name_hits, name)
                if picked is None and len(name_hits) == 1:
                    picked = name_hits[0]
                if picked:
                    return await self._load_with_character(picked.player_id, character)

        if not hits:
            return None, f"没有找到「{query}」。"
        if len(hits) == 1:
            return await self._load_with_character(hits[0].player_id, "")
        return None, self._hits_text(hits)

    async def _load_with_character(
        self, player_id: str, character_name: str
    ) -> tuple[Optional[PlayerProfile], str]:
        profile = await self._profile(player_id)
        character_name = character_name.strip()
        if not character_name:
            return profile, ""
        slot = pick_character(profile.characters, character_name)
        if slot is None:
            names = "、".join(character_zh(item.name) for item in profile.characters[:24]) or "（没有记录）"
            known = resolve_character(character_name)
            if known:
                return None, f"这个玩家没有{character_zh(known)}的记录。\n已有角色：{names}"
            return None, f"没有找到角色「{character_name}」。\n已有角色：{names}"
        if slot.character_id and slot.character_id != profile.character_id:
            profile = await self._profile(player_id, slot.character_id)
        return profile, ""

    async def _send_card(self, event: AstrMessageEvent, profile: PlayerProfile, prefix: str = ""):
        path = await self._build_card(profile)
        chain = [Comp.Image.fromFileSystem(path)]
        if prefix:
            chain.append(Comp.Plain(prefix))
        try:
            yield event.chain_result(chain)
        except Exception:
            logger.exception("chain 发图失败，回退 image_result")
            yield event.image_result(path)
            if prefix:
                yield event.plain_result(prefix)

    def _help_text(self) -> str:
        return "\n".join(
            [
                "GBVSR 段位查询",
                "群聊请 @ 我",
                "gbvsr <玩家名或ID>",
                "gbvsr <玩家名或ID> <角色名>",
                "角色名可以用中文、别称或英文，例如伊德、希斯、Id",
                "gbvsr（查询已绑定的玩家）",
                "gbvsr绑定 <玩家名或ID>",
                "gbvsr解绑",
                "gbvsr排行 [角色] [人数] [赛季N]",
                "默认前 10，最多 50。例如 gbvsr排行 伊德 20 赛季14",
                "gbvsr胜率 [角色] [大师]",
                "不写角色则发送全部角色对位胜率表。例如 gbvsr胜率 伊德",
                "gbvsr帮助",
                "",
                "数据来自 puddle.farm，段位和立绘以该站页面为准。",
            ]
        )

    @filter.event_message_type(filter.EventMessageType.ALL, priority=15)
    async def on_mention_command(self, event: AstrMessageEvent):
        if not self._should_handle(event):
            return

        self._reload_settings()
        text = self._extract_command_text(event)
        cmd, args = self._match_command(text)
        if not cmd:
            return

        try:
            if cmd == "gbvsr帮助":
                yield event.plain_result(self._help_text())
            elif cmd == "gbvsr解绑":
                async for result in self._handle_unbind(event):
                    yield result
            elif cmd == "gbvsr绑定":
                async for result in self._handle_bind(event, args):
                    yield result
            elif cmd in {"gbvsr排行", "gbvsr排行榜"}:
                async for result in self._handle_board(event, args):
                    yield result
            elif cmd == "gbvsr胜率":
                async for result in self._handle_rates(event, args):
                    yield result
            else:
                async for result in self._handle_query(event, args):
                    yield result
        except PuddleError as exc:
            yield event.plain_result(str(exc))
        except Exception:
            logger.exception("GBVSR 查询失败")
            yield event.plain_result("查询失败，请稍后再试。")
        event.stop_event()

    async def _handle_unbind(self, event: AstrMessageEvent):
        sender = self._sender_id(event)
        if not sender:
            yield event.plain_result("没有读到你的用户 ID，无法解绑。")
            return
        bindings = self._load_bindings()
        if sender not in bindings:
            yield event.plain_result("你还没有绑定 GBVSR 玩家。")
            return
        removed = bindings.pop(sender)
        _write_json(self.bindings_path, bindings)
        name = removed.get("name") if isinstance(removed, dict) else ""
        label = f"：{name}" if name else ""
        yield event.plain_result(f"已解除绑定{label}。")

    async def _handle_bind(self, event: AstrMessageEvent, args: str):
        if self._cooling_down(event):
            yield event.plain_result("查询有点频繁，请稍后再试。")
            return
        query = args.strip()
        if not query:
            yield event.plain_result("用法：gbvsr绑定 <玩家名或ID>")
            return
        self._mark_query(event)
        profile, message = await self._resolve_query(query)
        if message and profile is None:
            yield event.plain_result(message)
            return
        if profile is None:
            yield event.plain_result("没有绑定到玩家。")
            return
        sender = self._sender_id(event)
        if not sender:
            yield event.plain_result("没有读到你的用户 ID，无法绑定。")
            return
        bindings = self._load_bindings()
        bindings[sender] = {
            "player_id": profile.player_id,
            "name": profile.name,
            "platform": profile.platform,
        }
        _write_json(self.bindings_path, bindings)
        prefix = f"已绑定 {profile.name}"
        async for result in self._send_card(event, profile, prefix):
            yield result

    async def _handle_query(self, event: AstrMessageEvent, args: str):
        if self._cooling_down(event):
            yield event.plain_result("查询有点频繁，请稍后再试。")
            return
        query = args.strip()
        if not query:
            sender = self._sender_id(event)
            stored = self._load_bindings().get(sender) if sender else None
            if not isinstance(stored, dict) or not stored.get("player_id"):
                yield event.plain_result(
                    "用法：gbvsr <玩家名或ID>\n绑定自己：gbvsr绑定 <玩家名或ID>"
                )
                return
            query = str(stored["player_id"])
        self._mark_query(event)
        profile, message = await self._resolve_query(query)
        if message and profile is None:
            yield event.plain_result(message)
            return
        if profile is None:
            yield event.plain_result("没有找到这个玩家。")
            return
        async for result in self._send_card(event, profile):
            yield result

    def _parse_board_args(self, args: str) -> tuple[str, str, int, bool]:
        character_parts: list[str] = []
        season = ""
        limit = 10
        clamped = False
        for token in args.split():
            season_match = _SEASON_RE.fullmatch(token)
            if season_match:
                season = next(group for group in season_match.groups() if group)
                continue
            if token.isdigit():
                limit = int(token)
                continue
            character_parts.append(token)
        if limit < 1:
            limit = 1
        if limit > _BOARD_LIMIT:
            limit = _BOARD_LIMIT
            clamped = True
        return " ".join(character_parts), season, limit, clamped

    def _parse_rate_args(self, args: str) -> tuple[str, str]:
        cohort = "all"
        parts: list[str] = []
        for token in args.split():
            folded = token.casefold()
            if token in {"大师", "宗师"} or folded == "master":
                cohort = "master"
            elif token in {"全部", "全段"} or folded == "all":
                cohort = "all"
            else:
                parts.append(token)
        return " ".join(parts), cohort

    async def _images_by_url(self, urls: list[str]) -> dict[str, Any]:
        unique: list[str] = []
        seen: set[str] = set()
        for url in urls:
            if url and url not in seen:
                seen.add(url)
                unique.append(url)
        images = await self._load_images(unique)
        return {url: image for url, image in zip(unique, images) if image is not None}

    async def _send_image(self, event: AstrMessageEvent, path: str, note: str = ""):
        chain = [Comp.Image.fromFileSystem(path)]
        if note:
            chain.append(Comp.Plain(note))
        try:
            yield event.chain_result(chain)
        except Exception:
            logger.exception("chain 发图失败，回退 image_result")
            yield event.image_result(path)
            if note:
                yield event.plain_result(note)

    async def _handle_board(self, event: AstrMessageEvent, args: str):
        if self._cooling_down(event):
            yield event.plain_result("查询有点频繁，请稍后再试。")
            return
        character_query, season, limit, clamped = self._parse_board_args(args)
        character_key = ""
        character_label = "全角色"
        if character_query:
            english = resolve_character(character_query)
            character_key = character_id(character_query) or ""
            if not english or not character_key:
                yield event.plain_result(f"没有找到角色「{character_query}」。")
                return
            character_label = character_zh(english)
        self._mark_query(event)
        cache_key = f"board:{character_key}:{season}"
        cached = self._cache_get(cache_key)
        if cached is None:
            rows, current_season, sky_url = await self.client.leaderboard(character_key, season)
            cached = (rows, current_season, sky_url)
            self._cache_set(cache_key, cached)
        rows, current_season, sky_url = cached
        shown = list(rows[:limit])
        if not shown:
            yield event.plain_result("这个排行榜还没有玩家。")
            return
        portraits = await self._images_by_url(
            [row.portrait_url for row in shown] + [sky_url]
        )
        icons = await self._images_by_url([row.rank_icon_url for row in shown])
        season_label = f"第{current_season}赛季" if current_season else "当前赛季"
        title = "排行榜"
        subtitle = f"{character_label} · {season_label} · 前{len(shown)}"
        out_path = os.path.join(
            self.card_dir,
            f"board_{character_key or 'all'}_{current_season or 'now'}_{limit}_{int(time.time() * 1000)}.png",
        )
        await asyncio.to_thread(
            render_leaderboard,
            shown,
            out_path,
            title,
            subtitle,
            portraits,
            icons,
            portraits.get(sky_url),
            character_zh,
            rank_zh,
        )
        self._sweep_temp_files()
        note = f"最多显示前 {_BOARD_LIMIT} 名。" if clamped else ""
        async for result in self._send_image(event, out_path, note):
            yield result

    async def _handle_matrix(self, event: AstrMessageEvent, cohort: str):
        cache_key = f"matrix:{cohort}"
        matrix = self._cache_get(cache_key)
        if matrix is None:
            matrix = await self.client.matchup_matrix(cohort)
            self._cache_set(cache_key, matrix)
        cohort_label = "大师及以上" if matrix.cohort == "master" or cohort == "master" else "全部对局"
        portraits = await self._images_by_url(
            [slot.portrait_url for slot in matrix.columns]
            + [slot.portrait_url for slot, _cells in matrix.rows]
        )
        out_path = os.path.join(
            self.card_dir,
            f"matrix_{cohort}_{int(time.time() * 1000)}.png",
        )
        await asyncio.to_thread(
            render_matrix,
            matrix,
            out_path,
            "角色对位胜率",
            f"行对列 · {cohort_label} · 近30天排位",
            portraits,
            character_zh,
        )
        self._sweep_temp_files()
        async for result in self._send_image(event, out_path):
            yield result

    async def _handle_rates(self, event: AstrMessageEvent, args: str):
        if self._cooling_down(event):
            yield event.plain_result("查询有点频繁，请稍后再试。")
            return
        character_query, cohort = self._parse_rate_args(args)
        english = ""
        character_key = "0"
        if character_query:
            english = resolve_character(character_query) or ""
            character_key = character_id(character_query) or ""
            if not english or not character_key:
                yield event.plain_result(f"没有找到角色「{character_query}」。")
                return
        self._mark_query(event)
        if not character_query:
            async for result in self._handle_matrix(event, cohort):
                yield result
            return
        cache_key = f"rates:{character_key}:{cohort}"
        report = self._cache_get(cache_key)
        if report is None:
            report = await self.client.matchups(character_key, cohort)
            self._cache_set(cache_key, report)
        cohort_label = "大师及以上" if report.cohort == "master" or cohort == "master" else "全部对局"
        rows = sorted(report.matchups, key=lambda item: _rate_value(item.win_rate), reverse=True)
        overall = next(
            (item for item in report.overall if item.character.casefold() == english.casefold()),
            None,
        )
        summary = ""
        if overall:
            summary = f"总胜率 {overall.win_rate} · {overall.matches}场 · "
        title = f"{character_zh(english)} 对位胜率"
        subtitle = f"{summary}{cohort_label}"
        if not rows:
            yield event.plain_result("没有读到胜率数据。")
            return
        portraits = await self._images_by_url(
            [row.portrait_url for row in rows] + [report.sky_url]
        )
        out_path = os.path.join(
            self.card_dir,
            f"rates_{character_key}_{cohort}_{int(time.time() * 1000)}.png",
        )
        await asyncio.to_thread(
            render_rates,
            rows,
            out_path,
            title,
            subtitle,
            portraits,
            portraits.get(report.sky_url),
            character_zh,
            True,
        )
        self._sweep_temp_files()
        async for result in self._send_image(event, out_path):
            yield result


def _rate_value(rate: str) -> float:
    try:
        return float(rate.replace("%", "").replace(",", "").strip())
    except ValueError:
        return -1.0
