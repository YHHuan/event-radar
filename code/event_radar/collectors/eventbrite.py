"""Eventbrite collector — 同 Accupass 方法學:列表頁(SSR)發現 URL → 詳情頁 JSON-LD。

台灣 Eventbrite 偏國際/外語/社群/科技活動,補其他來源沒有的。列表 SSR 有 /e/...-tickets-<id>
連結,詳情頁有 schema.org/Event JSON-LD。過濾線上活動 + 只留台北/新北 + 未來90天。
"""
from __future__ import annotations

import json
import re
import time
from datetime import date, datetime, timedelta

import requests

from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (event-radar/0.1; personal)"}
SOURCE_NAME = "Eventbrite"
TARGET_CITIES = {"台北市", "新北市"}

_LD_RE = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_EVENT_URL_RE = re.compile(r'https://www\.eventbrite\.[a-z.]+/e/[a-z0-9-]+-tickets-\d+')
_LIST_URLS = [
    "https://www.eventbrite.com/d/taiwan--taipei/all-events/",
    "https://www.eventbrite.com/d/taiwan--new-taipei/all-events/",
]


def _cfg() -> dict:
    return sources().get("eventbrite", {}) or {}


def _discover() -> list[str]:
    urls: list[str] = []
    for lu in _cfg().get("list_urls") or _LIST_URLS:
        try:
            html = requests.get(lu, headers=HEADERS, timeout=TIMEOUT).text
        except Exception as e:  # noqa: BLE001
            print(f"  [eventbrite] list FAIL: {e}")
            continue
        urls += _EVENT_URL_RE.findall(html)
        time.sleep(1)
    return list(dict.fromkeys(u.split("?")[0] for u in urls))


def _event_ld(html: str) -> dict | None:
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
    ld = _event_ld(html)
    if not ld:
        return None
    loc = ld.get("location") or {}
    if isinstance(loc, list):
        loc = loc[0] if loc else {}
    if not isinstance(loc, dict):
        loc = {}
    # 線上活動跳過(無實體台北場)
    if "VirtualLocation" in str(loc.get("@type", "")):
        return None
    venue = clean_text(loc.get("name"))
    addr = loc.get("address")
    address = ""
    if isinstance(addr, dict):
        address = clean_text(
            " ".join(
                str(addr.get(k, "")) for k in ("streetAddress", "addressLocality", "addressRegion")
            )
        )
    elif isinstance(addr, str):
        address = clean_text(addr)
    city = detect_city(address, venue)
    org = ld.get("organizer") or {}
    organizer = clean_text(org.get("name")) if isinstance(org, dict) else ""
    return {
        "source_name": SOURCE_NAME,
        "title": clean_text(ld.get("name")),
        "organizer": organizer,
        "category": None,
        "description_clean": clean_text(ld.get("description"))[:2000],
        "source_url": url,
        "ticket_url": url,
        "image_url": (ld.get("image") if isinstance(ld.get("image"), str) else None),
        "city": city,
        "tags": [],
        "performances": [
            {
                "start_time": parse_dt((ld.get("startDate") or "")[:19].replace("T", " ")),
                "end_time": parse_dt((ld.get("endDate") or "")[:19].replace("T", " ")),
                "venue_name": venue,
                "venue_address": address,
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
    urls = _discover()[: cfg.get("max_fetch", 40)]
    today = date.today()
    horizon = today + timedelta(days=90)
    out: list[dict] = []
    for url in urls:
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            ev = _to_event(url, r.text)
        except Exception as e:  # noqa: BLE001
            print(f"  [eventbrite] {url[-30:]} FAIL: {e}")
            continue
        time.sleep(1)
        if not ev or not ev["title"] or ev["city"] not in TARGET_CITIES:
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
    print(f"  [eventbrite] -> {len(out)} events (台北/新北,未來90天) from {len(urls)} urls")
    return out
