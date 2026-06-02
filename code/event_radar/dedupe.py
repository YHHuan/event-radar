"""去重複 key。同一活動跨來源(KKTIX/主辦IG/文化部)合併成一張卡。"""
from __future__ import annotations

import hashlib
import re
import unicodedata

_NORM_RE = re.compile(r"[\s\-_·,，。、!！?？:：()()【】\[\]「」『』~～\"'’“”/／]+")
_TITLE_DROP_TOKENS = (
    "台北場",
    "臺北場",
    "新北場",
    "台北",
    "臺北",
    "新北",
)
_CITY_ALIASES = {
    "台北": "台北市",
    "臺北": "台北市",
    "台北市": "台北市",
    "臺北市": "台北市",
    "新北": "新北市",
    "新北市": "新北市",
    "基隆": "基隆市",
    "基隆市": "基隆市",
    "桃園": "桃園市",
    "桃園市": "桃園市",
}
_VENUE_DROP_TOKENS = (
    "國家",
    "市立",
    "市政府",
    "市政",
    "政府",
    "藝術文化",
    "文化",
    "中心",
    "大樓",
    "園區",
    "場館",
    "歌劇院",
    "音樂廳",
    "演奏廳",
    "表演廳",
    "演藝廳",
    "實驗劇場",
    "大劇院",
    "小劇場",
    "劇場",
    "展演館",
    "展覽館",
    "美術館",
    "博物館",
    "會議廳",
    "講堂",
    "廳",
    "館",
)


def _norm_text(text: str | None) -> str:
    t = unicodedata.normalize("NFKC", text or "")
    t = t.replace("臺", "台").casefold()
    t = _NORM_RE.sub("", t)
    return t


def normalize_title(title: str | None) -> str:
    t = _norm_text(title)
    for n in _TITLE_DROP_TOKENS:
        t = t.replace(n.lower(), "")
    return t


def normalize_city(city: str | None) -> str:
    t = unicodedata.normalize("NFKC", city or "").replace("臺", "台").strip()
    return _CITY_ALIASES.get(t, t)


def normalize_venue(venue: str | None) -> str:
    """場館名稱正規化備用:同一場館常見前綴/修飾詞不應影響判斷。"""
    t = _norm_text(venue)
    for token in _VENUE_DROP_TOKENS:
        t = t.replace(_norm_text(token), "")
    return t


def dedupe_key(
    title: str | None,
    first_start: str | None,
    city: str | None,
    n_performances: int = 1,
) -> str:
    """去重 key = 標題正規化 + 城市 (+ 單場才加首場日期)。

    多場次製作(n>1)**不含日期**:長檔演出每天位移「最早未來場次」會讓含日期的 key
    漂移、同一齣戲裂成多張卡(719/3351 bug)。單場(n==1)才用日期,以區分每月固定的
    open mic / 走讀等同名不同日活動。場館一律不進 key(避免前綴誤合/漏合)。
    """
    norm = normalize_title(title)
    c = normalize_city(city)
    if (n_performances or 1) > 1:
        raw = f"{norm}|{c}"
    else:
        raw = f"{norm}|{(first_start or '')[:10]}|{c}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def perf_key(start_time: str | None, venue: str | None) -> str:
    raw = f"{start_time or ''}|{(venue or '').strip()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
