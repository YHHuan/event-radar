"""OPENTIX public listing collector.

Only reads public event/detail pages, no login-only endpoints.
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urljoin

import requests

from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 25
HEADERS = {"User-Agent": "event-radar/0.1 (personal)"}
SOURCE_NAME = "OPENTIX"
MAX_DETAIL_FETCHES = 40
MAX_EVENTS = 40
TARGET_CITIES = {"台北市", "新北市"}

_EVENT_HREF_RE = re.compile(r"/event/\d+")
_DATE_RANGE_RE = re.compile(
    r"(?P<title>.+?)\s+"
    r"(?P<start>20\d{2}/\d{1,2}/\d{1,2})\s*\([^)]*\)\s*-\s*"
    r"(?P<end>20\d{2}/\d{1,2}/\d{1,2})"
)
_PHONE_RE = re.compile(r"\b0\d{1,2}-?\d{3,4}-?\d{3,4}\b")


class _PageParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self.text_chunks: list[str] = []
        self._href_stack: list[str | None] = []
        self._link_text: list[str] = []
        self.meta: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "a":
            self._href_stack.append(attr.get("href"))
            self._link_text = []
        elif tag == "meta":
            key = attr.get("property") or attr.get("name")
            content = attr.get("content")
            if key and content:
                self.meta[key] = content

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href_stack:
            href = self._href_stack.pop()
            text = clean_text(" ".join(self._link_text))
            if href and text:
                self.links.append((href, text))
            self._link_text = []

    def handle_data(self, data: str) -> None:
        text = clean_text(unescape(data))
        if not text:
            return
        self.text_chunks.append(text)
        if self._href_stack:
            self._link_text.append(text)

    @property
    def text(self) -> str:
        return clean_text(" ".join(self.text_chunks))


def collect() -> list[dict]:
    cfg = _platform_config()
    if not cfg or not cfg.get("enabled"):
        return []
    base_url = cfg.get("url") or "https://www.opentix.life/event"

    try:
        listing = _fetch(base_url)
    except Exception as e:  # noqa: BLE001
        print(f"  [opentix] listing FAIL: {e}")
        return []

    candidates = _parse_listing(listing, base_url)
    out: list[dict] = []
    fetched = 0
    for item in candidates:
        if fetched >= MAX_DETAIL_FETCHES or len(out) >= MAX_EVENTS:
            break
        fetched += 1
        time.sleep(1)
        try:
            detail = _fetch(item["source_url"])
            ev = _to_event(item, detail)
        except Exception as e:  # noqa: BLE001
            print(f"  [opentix] detail FAIL {item['source_url']}: {e}")
            continue
        if ev["city"] not in TARGET_CITIES:
            continue
        out.append(ev)
    return out


def _platform_config() -> dict | None:
    for cfg in sources().get("platforms", []):
        if cfg.get("source_name") == SOURCE_NAME:
            return cfg
    return None


def _fetch(url: str) -> str:
    r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    return r.text


def _parse_listing(html: str, base_url: str) -> list[dict]:
    parser = _PageParser()
    parser.feed(html)
    seen: set[str] = set()
    items: list[dict] = []
    today = date.today()
    horizon = today + timedelta(days=90)

    for href, text in parser.links:
        if not _EVENT_HREF_RE.search(href):
            continue
        m = _DATE_RANGE_RE.search(text)
        if not m:
            continue
        start_date = _date(m.group("start"))
        if not start_date or start_date < today or start_date > horizon:
            continue
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        items.append(
            {
                "title": clean_text(m.group("title")),
                "start_time": parse_dt(m.group("start")),
                "end_time": parse_dt(m.group("end")),
                "source_url": url,
            }
        )
    return sorted(items, key=lambda x: x["start_time"] or "")


def _to_event(item: dict, html: str) -> dict:
    parser = _PageParser()
    parser.feed(html)
    text = parser.text
    category = _between(text, "類別：", "分級：") or _between(text, "類別：", "主辦：")
    organizer = _clean_organizer(_between(text, "主辦：", "收藏"))
    venue_name = _between(text, "選擇場館", "場館地址：")
    venue_address = _between(text, "場館地址：", "地圖")
    description = _between(text, "節目介紹", "折扣方案") or _between(text, "節目介紹", "重要須知")
    city = detect_city(venue_address or "", venue_name or "", text)
    image_url = parser.meta.get("og:image")
    price_text = _extract_price(text)

    return {
        "source_name": SOURCE_NAME,
        "title": item["title"],
        "organizer": organizer,
        "category": category,
        "description_clean": description[:2000] if description else "",
        "source_url": item["source_url"],
        "ticket_url": item["source_url"],
        "image_url": image_url,
        "city": city,
        "tags": [category] if category else [],
        "performances": [
            {
                "start_time": item["start_time"],
                "end_time": item["end_time"],
                "venue_name": venue_name,
                "venue_address": venue_address,
                "latitude": None,
                "longitude": None,
                "city": city,
                "price_text": price_text,
                "is_ticketed": 0 if "本節目已下架" in text else 1,
                "availability_text": None,
            }
        ],
    }


def _date(s: str) -> date | None:
    try:
        return datetime.strptime(s, "%Y/%m/%d").date()
    except ValueError:
        return None


def _between(text: str, start: str, end: str) -> str | None:
    if start not in text:
        return None
    tail = text.split(start, 1)[1]
    if end in tail:
        tail = tail.split(end, 1)[0]
    return clean_text(tail)


def _clean_organizer(s: str | None) -> str | None:
    if not s:
        return None
    s = _PHONE_RE.sub("", s)
    return clean_text(s) or None


def _extract_price(text: str) -> str | None:
    m = re.search(r"(?:票價|票券|票種)[:：]?\s*([^。；;\n]{1,80})", text)
    return clean_text(m.group(0)) if m else None
