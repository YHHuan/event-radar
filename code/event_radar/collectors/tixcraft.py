"""拓元售票 tixcraft collector — 國際演唱會/世貿大型展/大型音樂活動主場。

/activity 是 SSR,listing 區塊(eventbl)直接含 日期/標題/場館/detail 連結,免抓詳情頁。
拓元是全國性,於來源端只留 台北/新北(其餘他縣市本來就會被 rules demote,不灌進來)。
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta

import requests

from ..cards import cards_in
from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (event-radar/0.1; personal)"}
SOURCE_NAME = "拓元tixcraft"
BASE = "https://tixcraft.com"
TARGET_CITIES = {"台北市", "新北市"}

_BLOCK_RE = re.compile(
    r'<div class="eventbl.*?(?=<div class="eventbl|<div class="col-lg-12[^"]*text-center")',
    re.S,
)
_DETAIL_RE = re.compile(r'/activity/detail/([A-Za-z0-9_]+)')
_DATE_RE = re.compile(r'class="text-small date">\s*(20\d{2}/\d{1,2}/\d{1,2})')
_TITLE_RE = re.compile(r'class="text-bold[^"]*">\s*<a [^>]*>([^<]+)</a>')
_VENUE_RE = re.compile(r'class="text-small text-med-light">\s*([^<]+)')

# 票種/購票頁變體:剝括號取基礎標題。卡別專區(【Mastercard專區】/玉山卡友專區)不丟,
# 反而抽出卡別標在活動上(見 cards.py)。純物流頁(身心障礙/周邊/取貨)才丟棄。
_BRACKET_PREFIX_RE = re.compile(r"^\s*[【\[]([^】\]]*)[】\]]\s*")
_BRACKET_SUFFIX_RE = re.compile(r"\s*[【\[]([^】\]]*)[】\]]\s*$")
_NOISE_TOKENS = ("身心障礙", "輪椅", "愛心票", "購票頁面", "周邊", "現場取貨", "郵寄", "加購", "套票")
_SPONSOR_RE = re.compile(r"^.{0,8}?冠名贊助\s*")
_SECTION_SUFFIX_RE = re.compile(r"\s*\S{0,6}?(?:卡友|套票)?專區\s*$")


def _is_noise(raw: str) -> bool:
    """純物流/無障礙票頁(非活動本身、也非卡別訊號)。"""
    return any(tok in raw for tok in _NOISE_TOKENS)


def _base_title(raw: str) -> str:
    """剝括號/冠名贊助/卡友專區 等,取可分組的基礎標題。"""
    t = raw.strip()
    while (m := _BRACKET_PREFIX_RE.match(t)):
        t = t[m.end():].strip()
    while (m := _BRACKET_SUFFIX_RE.search(t)):
        t = t[: m.start()].strip()
    t = _SPONSOR_RE.sub("", t)
    t = _SECTION_SUFFIX_RE.sub("", t)
    return t.strip()

# 純場館名(無城市字)的台北/新北 fallback。detect_city 已處理中英文城市名,這裡補場館。
_TAIPEI_VENUE_KW = (
    "legacy", "the wall", "sub live", "sub (", "clapper", "moondog", "pipe live",
    "河岸留言", "riverside", "海邊的卡夫卡", "revolver", "witch house", "天母",
    "小巨蛋", "ticc", "國際會議中心", "華山", "松山文創", "松菸", "北流",
    "流行音樂中心", "西門紅樓", "中山堂", "城市舞台", "水源劇場", "三創", "syntrend",
)
_NEWTAIPEI_VENUE_KW = ("新莊", "板橋", "三重", "新店", "蘆洲", "中和", "永和")


def _venue_city(venue: str) -> str | None:
    city = detect_city(venue)
    if city:
        return city
    low = venue.lower()
    if any(kw in low for kw in _TAIPEI_VENUE_KW):
        return "台北市"
    if any(kw in venue for kw in _NEWTAIPEI_VENUE_KW):
        return "新北市"
    return None


def _cfg() -> dict:
    return sources().get("tixcraft", {}) or {}


def collect() -> list[dict]:
    if not _cfg().get("enabled"):
        return []
    try:
        r = requests.get(f"{BASE}/activity", headers=HEADERS, timeout=TIMEOUT)
        r.raise_for_status()
    except Exception as e:  # noqa: BLE001
        print(f"  [tixcraft] listing FAIL: {e}")
        return []

    today = date.today()
    horizon = today + timedelta(days=90)
    by_key: dict[tuple, dict] = {}  # (base_title, day) -> event;變體合併卡別到同一筆

    for block in _BLOCK_RE.findall(r.text):
        dm = _DETAIL_RE.search(block)
        tm = _TITLE_RE.search(block)
        if not dm or not tm:
            continue
        raw = clean_text(tm.group(1))
        cards = cards_in(raw)
        if not cards and _is_noise(raw):  # 純物流頁且非卡別訊號 → 丟
            continue
        title = _base_title(raw)
        if not title:
            continue
        date_m = _DATE_RE.search(block)
        start = parse_dt(date_m.group(1)) if date_m else None
        if date_m:
            try:
                d = datetime.strptime(date_m.group(1), "%Y/%m/%d").date()
                if d < today or d > horizon:
                    continue
            except ValueError:
                pass
        vm = _VENUE_RE.search(block)
        venue = clean_text(vm.group(1)) if vm else ""
        city = _venue_city(venue)
        if city not in TARGET_CITIES:
            continue
        key = (title, (start or "")[:10])
        ev = by_key.get(key)
        if ev is None:
            ev = {
                "source_name": SOURCE_NAME,
                "title": title,
                "organizer": None,
                "category": None,
                "description_clean": "",
                "source_url": f"{BASE}/activity/detail/{dm.group(1)}",
                "ticket_url": f"{BASE}/activity/detail/{dm.group(1)}",
                "image_url": None,
                "city": city,
                "tags": [],
                "_cards": set(),
                "performances": [
                    {
                        "start_time": start, "end_time": None,
                        "venue_name": venue, "venue_address": venue,
                        "latitude": None, "longitude": None, "city": city,
                        "price_text": None, "is_ticketed": 1, "availability_text": None,
                    }
                ],
            }
            by_key[key] = ev
        ev["_cards"].update(cards)

    out = []
    for ev in by_key.values():
        cardlist = sorted(ev.pop("_cards"))
        ev["tags"] = [f"💳{c}" for c in cardlist]
        out.append(ev)
    ncard = sum(1 for e in out if e["tags"])
    print(f"  [tixcraft] {len(out)} events (台北/新北,未來90天;{ncard} 有信用卡優惠)")
    return out
