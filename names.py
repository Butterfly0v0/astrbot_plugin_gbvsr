"""GBVSR character and rank names.

Display names are the official Simplified Chinese names from Granblue Fantasy
Versus: Rising. Aliases cover the wiki spellings and the nicknames players
actually type. English names stay valid.
"""

from __future__ import annotations

import re

# (English name on puddle.farm, 简中 display, extra aliases)
_CHARACTERS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Katalina", "卡塔莉娜", ("卡姐",)),
    ("Gran", "古兰", ("格兰", "团长")),
    ("Lancelot", "兰斯洛特", ("枪兵", "兰斯")),
    ("Charlotta", "夏洛特", ("夏绿蒂", "小夏", "豆丁")),
    ("Ladiva", "法斯蒂瓦", ("拉迪瓦", "汉女")),
    ("Ferry", "菲莉", ("鬼娘",)),
    ("Percival", "珀西瓦尔", ("帕西瓦尔", "炎帝")),
    ("Lowain", "罗艾因", ("小黄", "三傻")),
    ("Zeta", "塞达", ("泽塔", "瑟塔")),
    ("Metera", "梅忒拉", ("美黛拉", "梅提拉", "大姐")),
    ("Vaseraga", "巴萨拉卡", ("巴萨拉加", "瓦塞尔加", "大镰", "巴萨")),
    ("Beelzebub", "别西卜", ("巴布",)),
    ("Narmaya", "娜露梅", ("娜尔梅亚", "娜鲁梅亚", "蝴蝶", "刀妹", "奶刀")),
    ("Zooey", "佐伊", ("刀龙",)),
    ("Soriz", "索利兹", ("索利茲",)),
    ("Djeeta", "姬塔", ("女主",)),
    ("Belial", "彼列", ("贝利尔", "贝利", "贝", "老贝")),
    ("Cagliostro", "卡莉奥丝特罗", ("卡莉奥斯特萝", "老男人")),
    ("Yuel", "尤艾尔", ("尤埃尔", "狐狸")),
    ("Anre", "乌诺", ("枪爷", "一爷")),
    ("Eustace", "尤斯提斯", ("尤斯缇斯", "电狼")),
    ("Seox", "希斯", ("六", "西斯", "老六")),
    ("Avatar Belial", "堕天化身·彼列", ("阿凡达·贝利尔", "阿凡达贝利尔", "化身贝利尔", "堕落化身", "堕天化身", "A贝")),
    ("Vira", "薇拉", ("维拉",)),
    ("Anila", "安妮菈", ("阿妮拉", "羊")),
    ("Siegfried", "齐格飞", ("齐格菲", "齐格菲尔德", "龙骑", "飞哥")),
    ("Nier", "尼娅", ("妮雅",)),
    ("Grimnir", "格里姆尼尔", ("风神", "风军")),
    ("Lucilius", "路西法", ("路西菲尔",)),
    ("2B", "2B", ()),
    ("Versusia", "维萨西娅", ("灭赦", "龙妈")),
    ("Beatrix", "贝阿朵丽丝", ("贝雅特丽丝", "贝熊")),
    ("Vane", "巴恩", ("维恩", "范恩")),
    ("Vikala", "毗伽菈", ("碧卡拉", "鼠鼠")),
    ("Sandalphon", "圣德芬", ("咖啡", "芬")),
    ("Galleon", "伽莱翁", ("金龙", "土龙")),
    ("Wilnas", "威尔纳斯", ("红龙", "火龙")),
    ("Meg", "梅格", ()),
    ("Ilsa", "伊尔莎", ("教官",)),
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


# puddle.farm 角色筛选的 id，和网站 character 下拉框一致。
_CHARACTER_IDS = {
    "Katalina": "0",
    "Gran": "1",
    "Lancelot": "2",
    "Charlotta": "3",
    "Ladiva": "4",
    "Ferry": "5",
    "Percival": "6",
    "Lowain": "7",
    "Zeta": "8",
    "Metera": "9",
    "Vaseraga": "10",
    "Beelzebub": "11",
    "Narmaya": "12",
    "Zooey": "13",
    "Soriz": "14",
    "Djeeta": "15",
    "Belial": "16",
    "Cagliostro": "17",
    "Yuel": "18",
    "Anre": "19",
    "Eustace": "20",
    "Seox": "21",
    "Avatar Belial": "22",
    "Vira": "23",
    "Anila": "24",
    "Siegfried": "25",
    "Nier": "26",
    "Grimnir": "27",
    "Lucilius": "28",
    "2B": "29",
    "Versusia": "30",
    "Beatrix": "31",
    "Vane": "32",
    "Vikala": "33",
    "Sandalphon": "34",
    "Galleon": "35",
    "Wilnas": "36",
    "Meg": "37",
    "Ilsa": "38",
    "Id": "39",
}


def character_id(name: str) -> str | None:
    english = resolve_character(name)
    if not english:
        return None
    return _CHARACTER_IDS.get(english)


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
