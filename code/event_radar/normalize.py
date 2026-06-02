"""文字/日期/城市標準化。"""
from __future__ import annotations

import re
from datetime import datetime

from .config import profile

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_DATE_FORMATS = ("%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y/%m/%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = _TAG_RE.sub(" ", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&")
    return _WS_RE.sub(" ", s).strip()


def parse_dt(s: str | None) -> str | None:
    """回傳 ISO 'YYYY-MM-DDTHH:MM:SS' 或日期。失敗回 None。"""
    if not s:
        return None
    s = s.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).isoformat()
        except ValueError:
            continue
    return None


# 全台縣市(含異體字)。偵測「哪個縣市」用,讓 rules 能分辨 目標區/他縣市/未知。
_ALL_CITIES = {
    "台北市": ["台北", "臺北"], "新北市": ["新北"], "基隆市": ["基隆"],
    "桃園市": ["桃園"], "新竹市": ["新竹"], "新竹縣": [], "苗栗縣": ["苗栗"],
    "台中市": ["台中", "臺中"], "彰化縣": ["彰化"], "南投縣": ["南投"],
    "雲林縣": ["雲林"], "嘉義市": ["嘉義"], "嘉義縣": [], "台南市": ["台南", "臺南"],
    "高雄市": ["高雄"], "屏東縣": ["屏東"], "宜蘭縣": ["宜蘭"], "花蓮縣": ["花蓮"],
    "台東縣": ["台東", "臺東"], "澎湖縣": ["澎湖"], "金門縣": ["金門"], "連江縣": ["連江", "馬祖"],
}


# 英文城市(售票平台/國際場館常用)。"new taipei" 必須先於 "taipei" 判斷。
_ENGLISH_CITIES = [
    ("新北市", ["new taipei"]),
    ("台北市", ["taipei"]),
    ("桃園市", ["taoyuan"]),
    ("基隆市", ["keelung"]),
    ("新竹市", ["hsinchu"]),
    ("台中市", ["taichung"]),
    ("台南市", ["tainan"]),
    ("高雄市", ["kaohsiung"]),
    ("花蓮縣", ["hualien"]),
    ("宜蘭縣", ["yilan"]),
]


def detect_city(*texts: str) -> str | None:
    """回傳標準縣市名;偵測不到回 None(= 未知,非『他縣市』)。
    先比中文,再比英文(英文 new taipei 先於 taipei)。"""
    blob = " ".join(t for t in texts if t)
    if not blob:
        return None
    for canonical, variants in _ALL_CITIES.items():
        for v in [canonical] + variants:
            if v and v in blob:
                return canonical
    low = blob.lower()
    for canonical, variants in _ENGLISH_CITIES:
        if any(v in low for v in variants):
            return canonical
    return None
