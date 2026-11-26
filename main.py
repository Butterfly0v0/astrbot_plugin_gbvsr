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
COMMANDS = ("gbvsr帮助", "gbvsr绑定", "gbvsr解绑", "gbvsr")
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

PuddleClient = _client.PuddleClient
PuddleError = _client.PuddleError
PlayerProfile = _client.PlayerProfile
SearchHit = _client.SearchHit
pick_character = _client.pick_character
character_zh = _names.character_zh
rank_zh = _names.rank_zh
resolve_character = _names.resolve_character
CardData = _card.CardData
open_image = _card.open_image
render_card = _card.render_card


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


def _cleanup_cards(cache_dir: str, keep_latest: int = 30, max_age_sec: int = 86400) -> None:
    try:
        entries = []
        for name in os.listdir(cache_dir):
            path = os.path.join(cache_dir, name)
            if os.path.isfile(path) and name.lower().endswith(".png"):
                entries.append((os.path.getmtime(path), path))
        entries.sort(reverse=True)
        now = time.time()
        for index, (mtime, path) in enumerate(entries):
            if index >= keep_latest or now - mtime > max_age_sec:
                try:
                    os.remove(path)
                except OSError:
                    pass
    except OSError:
        pass


@register(
    "astrbot_plugin_gbvsr",
    "Butterfly0v0",
    "查询 puddle.farm 上的 GBVSR 玩家段位",
    "0.1.0",
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
        self._reload_settings()

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
        self.client = PuddleClient(self.timeout_sec)

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
                return open_image(handle.read())
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
        _cleanup_cards(self.card_dir)
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
        caption = profile.page_url
        if prefix:
            caption = f"{prefix}\n{caption}"
        try:
            yield event.chain_result(
                [Comp.Image.fromFileSystem(path), Comp.Plain(caption)]
            )
        except Exception:
            logger.exception("chain 发图失败，回退 image_result")
            yield event.image_result(path)
            yield event.plain_result(caption)

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
