"""GBVSR character and rank names.

Display names follow the Simplified Chinese roster used for Granblue Fantasy
Versus: Rising. Aliases cover the other official spellings and the nicknames
players actually type. English names stay valid.
"""

from __future__ import annotations

import re

# (English name on puddle.farm, 简中 display, extra aliases)
_CHARACTERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Katalina", "卡塔莉娜", ("卡姐",)),
    ("Gran", "古兰", ("格兰", "团长")),
    ("Lancelot", "兰斯洛特", ("枪兵",)),
    ("Charlotta", "夏洛特", ("夏绿蒂", "小夏")),
    ("Ladiva", "法斯蒂瓦", ("拉迪瓦",)),
    ("Ferry", "菲莉", ("鬼娘",)),
    ("Percival", "帕西瓦尔", ("珀西瓦尔", "炎帝")),
    ("Lowain", "罗艾因", ("小黄",)),
    ("Zeta", "泽塔", ("塞达", "瑟塔")),
    ("Metera", "美黛拉", ("梅黛拉",)),
    ("Vaseraga", "巴萨拉卡", ("巴萨拉加", "瓦塞尔加", "大镰")),
    ("Beelzebub", "别西卜", ()),
    ("Narmaya", "娜尔梅亚", ("娜露梅", "娜鲁梅亚", "蝴蝶", "刀妹")),
    ("Zooey", "佐伊", ("刀龙",)),
    ("Soriz", "索利兹", ("索利茲",)),
    ("Djeeta", "姬塔", ("女主",)),
    ("Belial", "贝利尔", ("彼列", "贝利")),
    ("Cagliostro", "卡莉奥斯特萝", ("卡莉奥丝特罗", "老男人")),
    ("Yuel", "尤艾尔", ("尤埃尔",)),
    ("Anre", "乌诺", ("枪爷",)),
    ("Eustace", "尤斯缇斯", ("尤斯提斯",)),
    ("Seox", "希斯", ("六", "西斯")),
    ("Avatar Belial", "阿凡达·贝利尔", ("阿凡达贝利尔", "化身贝利尔", "堕落化身")),
    ("Vira", "维拉", ("薇拉",)),
    ("Anila", "阿妮拉", ("安妮菈", "羊")),
    ("Siegfried", "齐格飞", ("齐格菲", "齐格菲尔德", "龙骑")),
    ("Nier", "尼娅", ("妮雅",)),
    ("Grimnir", "格里姆尼尔", ("风神",)),
    ("Lucilius", "路西法", ("路西菲尔",)),
    ("2B", "2B", ()),
    ("Versusia", "维萨西娅", ("灭赦",)),
    ("Beatrix", "贝阿朵丽丝", ("贝雅特丽丝",)),
    ("Vane", "维恩", ("巴恩", "范恩")),
    ("Vikala", "碧卡拉", ("毗伽菈",)),
    ("Sandalphon", "圣德芬", ("咖啡",)),
    ("Galleon", "伽莱翁", ("金龙",)),
    ("Wilnas", "威尔纳斯", ("红龙",)),
    ("Meg", "梅格", ()),
    ("Ilsa", "伊尔莎", ()),
    ("Id", "伊德", ("伊度",)),
)

_RANK_ZH = {
    "grand master": "宗师",
    "gold master": "黄金大师",
    "silver master": "白银大师",
    "master": "大师",
}
_RANK_COMPACT = {key.replace(" ", ""): value for key, value in _RANK_ZH.items()}

_DISPLAY: dict[str, str] = {}
_EXACT: dict[str, set[str]] = {}
_NORMS: dict[str, set[str]] = {}


def _norm(text: str) -> str:
    text = text.casefold().strip()
    text = re.sub(r"[\s·・.．]+", "", text)
    return text


def _add(english: str, text: str) -> None:
    key = _norm(text)
    if not key:
        return
    _EXACT.setdefault(key, set()).add(english)
    _NORMS.setdefault(english, set()).add(key)


for _english, _chinese, _aliases in _CHARACTERS:
    _DISPLAY[_english] = _chinese
    _add(_english, _english)
    _add(_english, _chinese)
    for _alias in _aliases:
        _add(_english, _alias)


def resolve_character(query: str) -> str | None:
    """Return the site's English character name, or None when it is not unique."""
    key = _norm(query)
    if not key:
        return None
    owners = _EXACT.get(key)
    if owners:
        if len(owners) == 1:
            return next(iter(owners))
        return None
    if len(key) < 2:
        return None
    hits: list[str] = []
    for english, norms in _NORMS.items():
        if any(key in name for name in norms):
            hits.append(english)
    if len(hits) == 1:
        return hits[0]
    return None


def character_zh(name: str) -> str:
    english = resolve_character(name)
    if english:
        return _DISPLAY.get(english, name)
    return name


def rank_zh(rank: str) -> str:
    key = re.sub(r"\s+", " ", rank).strip().casefold()
    if not key:
        return rank
    translated = _RANK_ZH.get(key) or _RANK_COMPACT.get(key.replace(" ", ""))
    return translated or rank
