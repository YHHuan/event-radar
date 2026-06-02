"""Accupass collector — 自動發現(搜尋頁 SSR) + 貼連結。個別 event 頁有 JSON-LD。

來源 URL:
  1. **搜尋發現**:`/search?q=<品味關鍵字>&area=north` 是 SSR,每關鍵字回 ~25 event 連結。
     area=north=北台灣。關鍵字鎖 Accupass 的強項(真人圖書館/街遊/市集/料理體驗/走讀…)。
  2. inbox 表中未解析的 accupass 連結(Salmon 在 Streamlit 貼)
  3. sources.yaml 的 accupass.seed_urls(初始種子)
event 頁有 schema.org/Event 的 JSON-LD:name/startDate/endDate/location/organizer。
全國性 → 來源端只留 台北/新北 + 未來90天(JSON-LD 解析後過濾)。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta
from urllib.parse import quote

import requests

from .. import db
from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (event-radar/0.1; personal)"}
SOURCE_NAME = "Accupass"
TARGET_CITIES = {"台北市", "新北市"}

_LD_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_OG_IMG_RE = re.compile(r'og:image"[^>]*content="([^"]+)"')
_EVENT_SLUG_RE = re.compile(r'/event/([a-z0-9]+)')

# Accupass 強項品味關鍵字(culture.tw/拓元 抓不到的「酷東西」)
_DEFAULT_KEYWORDS = [
    "真人圖書館", "街遊", "走讀", "市集", "二手", "料理體驗", "共食",
    "獨立音樂", "open mic", "單口喜劇", "即興", "夜間生態", "工作坊", "選物",
]


def _discover_urls(keywords: list[str], per_kw: int = 25) -> list[str]:
    """用搜尋頁(SSR)發現 event 連結。area=north 鎖北台灣。"""
    found: list[str] = []
    for kw in keywords:
        url = f"https://www.accupass.com/search?q={quote(kw)}&area=north"
        try:
            html = requests.get(url, headers=HEADERS, timeout=TIMEOUT).text
        except Exception as e:  # noqa: BLE001
            print(f"  [accupass] search '{kw}' FAIL: {e}")
            continue
        slugs = list(dict.fromkeys(_EVENT_SLUG_RE.findall(html)))[:per_kw]
        found += [f"https://www.accupass.com/event/{s}" for s in slugs]
        time.sleep(1)  # 慢爬,有禮貌
    return found


def _gather_urls(cfg: dict) -> list[str]:
    urls: list[str] = []
    if cfg.get("discover", True):
        kws = cfg.get("search_keywords") or _DEFAULT_KEYWORDS
        urls += _discover_urls(kws, cfg.get("per_keyword", 25))
    urls += cfg.get("seed_urls", []) or []
    try:  # inbox 中未解析的 accupass 連結
        with db.connect() as conn:
            rows = conn.execute(
                "SELECT url FROM inbox WHERE parsed=0 AND url LIKE '%accupass.com/event%'"
            ).fetchall()
        urls += [r["url"] for r in rows]
    except Exception:  # noqa: BLE001
        pass
    # 去重(用 /event/<slug> 正規化)
    seen, clean = set(), []
    for u in urls:
        base = u.split("?")[0].rstrip("/")
        if base and base not in seen:
            seen.add(base)
            clean.append(u)
    return clean


def _find_event_ld(html: str) -> dict | None:
    for block in _LD_RE.findall(html):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        for item in (data if isinstance(data, list) else [data]):
            if isinstance(item, dict) and "Event" in str(item.get("@type", "")):
                return item
    return None


def _to_event(url: str, html: str) -> dict | None:
    ld = _find_event_ld(html)
    if not ld:
        return None
    loc = ld.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    venue_name = clean_text(loc.get("name")) if isinstance(loc, dict) else ""
    address = clean_text(loc.get("address")) if isinstance(loc, dict) else ""
    if isinstance(loc.get("address"), dict):
        address = clean_text(loc["address"].get("streetAddress") or loc["address"].get("name"))
    org = ld.get("organizer") or {}
    organizer = clean_text(org.get("name")) if isinstance(org, dict) else clean_text(str(org))
    city = detect_city(address, venue_name)
    img_m = _OG_IMG_RE.search(html)
    offers = ld.get("offers") or {}
    price = ""
    if isinstance(offers, dict):
        price = clean_text(str(offers.get("price") or offers.get("lowPrice") or ""))

    return {
        "source_name": SOURCE_NAME,
        "title": clean_text(ld.get("name")),
        "organizer": organizer,
        "category": None,
        "description_clean": clean_text(ld.get("description"))[:2000],
        "source_url": url.split("?")[0],
        "ticket_url": url.split("?")[0],
        "image_url": img_m.group(1) if img_m else None,
        "city": city,
        "tags": [],
        "performances": [
            {
                "start_time": parse_dt((ld.get("startDate") or "")[:19].replace("T", " ")),
                "end_time": parse_dt((ld.get("endDate") or "")[:19].replace("T", " ")),
                "venue_name": venue_name,
                "venue_address": address,
                "latitude": None,
                "longitude": None,
                "city": city,
                "price_text": price or None,
                "is_ticketed": 1,
                "availability_text": None,
            }
        ],
    }


def collect() -> list[dict]:
    cfg = sources().get("accupass", {}) or {}
    if not cfg.get("enabled"):
        return []
    urls = _gather_urls(cfg)[: cfg.get("max_fetch", 80)]
    today = date.today()
    horizon = today + timedelta(days=90)
    out: list[dict] = []
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            ev = _to_event(url, r.text)
        except Exception as e:  # noqa: BLE001
            print(f"  [accupass] {url[:50]} FAIL: {e}")
            continue
        time.sleep(1)
        if not ev or not ev["title"]:
            continue
        _mark_inbox_parsed(url)
        # 自動發現量大 → 來源端只留 台北/新北 + 未來90天(seed/inbox 一律保留)
        is_seed = url in (cfg.get("seed_urls") or []) or "inbox" in url
        if not is_seed:
            if ev["city"] not in TARGET_CITIES:
                continue
            first = ev["performances"][0]["start_time"]
            if first:
                try:
                    d = datetime.fromisoformat(first).date()
                    if d < today or d > horizon:
                        continue
                except ValueError:
                    pass
        out.append(ev)
    print(f"  [accupass] -> {len(out)} events (台北/新北,未來90天) from {len(urls)} urls")
    return out


def _mark_inbox_parsed(url: str) -> None:
    try:
        with db.connect() as conn:
            conn.execute("UPDATE inbox SET parsed=1 WHERE url=?", (url,))
    except Exception:  # noqa: BLE001
        pass
