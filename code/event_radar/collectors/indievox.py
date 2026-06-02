"""iNDIEVOX collector — 台灣獨立音樂售票平台(後搖/獨立/livehouse/發片專場主場)。

列表 /activity 是 SSR,按日期分組(panel-heading 日期 + activity/detail 連結 + img alt 標題)。
詳情頁無 JSON-LD,但有 og:title/og:image + 「地點」「票價」文字。robots 允許 /activity。
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

import requests

from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 20
HEADERS = {"User-Agent": "Mozilla/5.0 (event-radar/0.1; personal)"}
SOURCE_NAME = "iNDIEVOX"
BASE = "https://www.indievox.com"
MAX_DETAIL = 40
TARGET_CITIES = {"台北市", "新北市"}

_DATE_RE = re.compile(r'panel-heading">\s*<i class="fa fa-calendar"></i>\s*(20\d{2}/\d{1,2}/\d{1,2})')
_LINK_RE = re.compile(r'/activity/detail/([a-z0-9_]+)".{0,500}?alt="([^"]+)"', re.S)
_OG_TITLE_RE = re.compile(r'og:title"[^>]*content="([^"]+)"')
_OG_IMG_RE = re.compile(r'og:image"[^>]*content="([^"]+)"')
_TITLE_PREFIX_RE = re.compile(r'^\d{1,2}[./]\d{1,2}\s*[（(][^)）]*[)）]\s*')  # 去掉 "5.29(五) "


def _cfg() -> dict:
    return sources().get("indievox", {}) or {}


def _parse_listing(html: str) -> list[dict]:
    """回傳 [{slug,title,date}]:用 panel-heading 日期配對其後的 activity 連結。"""
    dates = [(m.start(), m.group(1)) for m in _DATE_RE.finditer(html)]
    items: list[dict] = []
    seen: set[str] = set()
    for m in _LINK_RE.finditer(html):
        pos, slug, alt = m.start(), m.group(1), m.group(2)
        if slug in seen:
            continue
        seen.add(slug)
        # 最近的前一個 panel-heading 日期
        d = None
        for dpos, dval in dates:
            if dpos <= pos:
                d = dval
            else:
                break
        title = _TITLE_PREFIX_RE.sub("", clean_text(alt))
        items.append({"slug": slug, "title": title, "date": d})
    return items


def _detail(slug: str) -> dict:
    url = f"{BASE}/activity/detail/{slug}"
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    html = r.text
    venue_block = _between(html, "地點", "</") or _between(html, "地址", "</") or ""
    venue_block = clean_text(re.sub(r"^[:：\s]+", "", venue_block))
    price = clean_text(_between(html, "票價", "</") or "")
    img = _OG_IMG_RE.search(html)
    og = _OG_TITLE_RE.search(html)
    return {
        "url": url,
        "venue": venue_block[:80],
        "price": price[:80] or None,
        "image": img.group(1) if img else None,
        "og_title": clean_text(og.group(1).replace("| iNDIEVOX", "")) if og else None,
    }


def _between(text: str, start: str, end: str) -> str | None:
    i = text.find(start)
    if i < 0:
        return None
    tail = text[i + len(start):]
    j = tail.find(end)
    return tail[:j] if j >= 0 else tail[:120]


def collect() -> list[dict]:
    cfg = _cfg()
    if not cfg.get("enabled"):
        return []
    today = date.today()
    horizon = today + timedelta(days=90)
    max_pages = cfg.get("max_pages", 1)  # iNDIEVOX ?page 無效(各頁同內容),只列近期~20場

    # 分頁抓列表(日期升序);整頁都超過時窗就停
    listing: list[dict] = []
    seen_slugs: set[str] = set()
    for page in range(1, max_pages + 1):
        try:
            r = requests.get(f"{BASE}/activity?page={page}", headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"  [indievox] listing page={page} FAIL: {e}")
            break
        page_items = [it for it in _parse_listing(r.text) if it["slug"] not in seen_slugs]
        if not page_items:
            break
        for it in page_items:
            seen_slugs.add(it["slug"])
        listing += page_items
        # 本頁最早日期已超過時窗 → 後面更晚,停(parse 成 date 比,避免字串序錯)
        page_dates = []
        for it in page_items:
            if it["date"]:
                try:
                    page_dates.append(datetime.strptime(it["date"], "%Y/%m/%d").date())
                except ValueError:
                    pass
        if page_dates and min(page_dates) > horizon:
            break
        time.sleep(1)
    out: list[dict] = []
    fetched = 0
    for it in listing:
        if fetched >= MAX_DETAIL:
            break
        start = parse_dt(it["date"]) if it["date"] else None
        # 先用列表日期粗篩時窗(省 detail 請求)
        if it["date"]:
            try:
                d = datetime.strptime(it["date"], "%Y/%m/%d").date()
                if d < today or d > horizon:
                    continue
            except ValueError:
                pass
        fetched += 1
        time.sleep(1)  # 慢慢爬
        try:
            det = _detail(it["slug"])
        except Exception as e:  # noqa: BLE001
            print(f"  [indievox] detail {it['slug']} FAIL: {e}")
            continue
        city = detect_city(det["venue"], it["title"])  # 標題也看(很多寫「台北場」)
        if city not in TARGET_CITIES:
            continue
        out.append(
            {
                "source_name": SOURCE_NAME,
                "title": det["og_title"] or it["title"],
                "organizer": None,
                "category": "獨立音樂",
                "description_clean": "",
                "source_url": det["url"],
                "ticket_url": det["url"],
                "image_url": det["image"],
                "city": city,
                "tags": ["獨立音樂"],
                "performances": [
                    {
                        "start_time": start,
                        "end_time": None,
                        "venue_name": det["venue"],
                        "venue_address": det["venue"],
                        "latitude": None,
                        "longitude": None,
                        "city": city,
                        "price_text": det["price"],
                        "is_ticketed": 1,
                        "availability_text": None,
                    }
                ],
            }
        )
    print(f"  [indievox] {len(out)} events (台北/新北,未來90天) from {len(listing)} listed")
    return out
