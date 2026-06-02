"""KKTIX collector — 走主辦子網域 feed,避開被 Cloudflare 擋的主站 kktix.com。

每個白名單主辦有 `<slug>.kktix.cc/events.json`(結構化近期活動清單)。
entry: url / published(ISO 起始) / title / summary / content(內含「時間：/地點：」) / author(主辦)。
slug 來自 sources.yaml 的 kktix.organizers(Salmon 提供主辦名稱 → 對應 slug)。
"""
from __future__ import annotations

import re
import time

import requests

from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (event-radar/0.1; personal)"}
SOURCE_NAME = "KKTIX"

_LOC_RE = re.compile(r"地點[:：]\s*(.+)")
_TIME_END_RE = re.compile(r"[~～]\s*(\d{1,2}:\d{2})")

# KKTIX 每個活動常有多列變體:票種/加購/周邊/取貨。這些不是獨立活動。
_BRACKET_RE = re.compile(r"^\s*[【\[]([^】\]]*)[】\]]\s*")
_NOISE_LABEL_TOKENS = (
    "福利", "加購", "加價購", "VIP", "SVIP", "GA", "現場取", "取貨",
    "郵寄", "周邊", "兌換", "盲鳥", "Upgrade", "預購", "限量福利",
)


def _strip_labels(title: str) -> tuple[str, list[str]]:
    """剝掉開頭連續的 【...】 標籤,回傳 (核心標題, 標籤list)。"""
    labels: list[str] = []
    t = title
    while True:
        m = _BRACKET_RE.match(t)
        if not m:
            break
        labels.append(m.group(1))
        t = t[m.end():]
    return t.strip(), labels


def _is_noise_variant(labels: list[str]) -> bool:
    low = " ".join(labels).lower()
    return any(tok.lower() in low for tok in _NOISE_LABEL_TOKENS)


def _cfg() -> dict:
    return sources().get("kktix", {}) or {}


def _entry_to_event(entry: dict, slug: str) -> dict | None:
    raw_title = clean_text(entry.get("title"))
    url = entry.get("url")
    if not raw_title or not url:
        return None
    # 剝票種/加購/周邊變體:noise 直接跳過,其餘去前綴(讓 dedupe 自動合併同活動)
    core, labels = _strip_labels(raw_title)
    if _is_noise_variant(labels):
        return None
    title = core or raw_title
    start = parse_dt((entry.get("published") or "")[:19].replace("T", " "))
    content = entry.get("content") or ""
    loc_m = _LOC_RE.search(content)
    venue = clean_text(loc_m.group(1)) if loc_m else ""
    city = detect_city(venue, content)
    author = entry.get("author")
    organizer = ""
    if isinstance(author, dict):
        organizer = clean_text(author.get("name"))
    elif isinstance(author, str):
        m = re.search(r"'name':\s*'([^']+)'", author)  # feed 偶爾把 dict 變字串
        organizer = m.group(1) if m else clean_text(author)

    return {
        "source_name": SOURCE_NAME,
        "title": title,
        "organizer": organizer,
        "category": None,
        "description_clean": clean_text(entry.get("summary"))[:2000],
        "source_url": url,
        "ticket_url": url,
        "image_url": None,
        "city": city,
        "tags": [],
        "performances": [
            {
                "start_time": start,
                "end_time": None,
                "venue_name": venue,
                "venue_address": venue,
                "latitude": None,
                "longitude": None,
                "city": city,
                "price_text": None,
                "is_ticketed": 1,
                "availability_text": None,
            }
        ],
    }


def collect() -> list[dict]:
    cfg = _cfg()
    if not cfg.get("enabled"):
        return []
    organizers = cfg.get("organizers", []) or []
    out: list[dict] = []
    for org in organizers:
        slug = org.get("slug") if isinstance(org, dict) else org
        if not slug:
            continue
        url = f"https://{slug}.kktix.cc/events.json"
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001 — fail-soft,單主辦失敗不影響其他
            print(f"  [kktix] {slug} FAIL: {e}")
            continue
        entries = data.get("entry", []) if isinstance(data, dict) else []
        seen: set[tuple] = set()
        n = 0
        for entry in entries:
            ev = _entry_to_event(entry, slug)
            if not ev:
                continue
            key = (ev["title"], (ev["performances"][0]["start_time"] or "")[:10])
            if key in seen:  # 同活動的票種變體已收過
                continue
            seen.add(key)
            out.append(ev)
            n += 1
        print(f"  [kktix] {slug} -> {n} events")
        time.sleep(1)  # 慢慢爬,有禮貌
    return out
