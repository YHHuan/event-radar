"""年代售票 + 寬宏售票 collector(同一套 UTK ASP.NET 後台,一個 parser 吃兩家)。

列表頁只有海報+連結(無日期/場館),需抓詳情頁。國際/大型演唱會、世貿展、動漫展、
玩具展、音樂會。全國性,於來源端只留 台北/新北。慢爬。
"""
from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

import requests

from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 25
HEADERS = {"User-Agent": "Mozilla/5.0 (event-radar/0.1; personal)"}
TARGET_CITIES = {"台北市", "新北市"}

_PID_RE = re.compile(r"PRODUCT_ID=([A-Za-z0-9]+)")
_TITLE_RE = re.compile(r"<title>(.*?)</title>", re.S)
_TAG_RE = re.compile(r"<[^>]+>")
# 演出日期 = 「YYYY/MM/DD(星期)HH:MM」(年代詳情頁的節目時間;非「時間：」開賣日)
_SHOW_DT_RE = re.compile(r"(20\d{2})/(\d{1,2})/(\d{1,2})\([^)]{1,3}\)\s*(\d{1,2}):(\d{2})")
# 地點:取第一個「非售票服務台」的
_LOC_ALL_RE = re.compile(r"地點[^<:：]{0,6}[:：]\s*(?:<[^>]+>)*\s*([^<\n]{2,50})")
_GENERIC_TITLES = ("寬宏售票系統", "年代售票系統", "年代售票", "寬宏售票", "寬宏藝術售票")


def _cfg() -> dict:
    return sources().get("era_kham", {}) or {}


def _clean_title(raw: str) -> str:
    t = clean_text(_TAG_RE.sub(" ", raw))
    for sep in ("｜", "|"):
        if sep in t:
            t = t.split(sep)[-1]
    return t.strip(" 「」　")


def _extract_start(html: str) -> str | None:
    """取最早的演出時間;排除售票截止(23:5x)。回 ISO 或 None。"""
    cands = []
    for m in _SHOW_DT_RE.finditer(html):
        y, mo, d, hh, mm = (int(x) for x in m.groups())
        if hh == 23 and mm >= 50:  # 售票截止日,跳過
            continue
        cands.append(f"{y:04d}/{mo:02d}/{d:02d} {hh:02d}:{mm:02d}")
    if not cands:
        return None
    return parse_dt(sorted(cands)[0])


def _extract_venue(html: str) -> str:
    for m in _LOC_ALL_RE.finditer(html):
        v = clean_text(m.group(1))
        if v and "售票服務台" not in v and "服務台" not in v:
            return v
    return ""


def _detail_to_event(site: str, base: str, pid: str, html: str) -> dict | None:
    title = _clean_title((_TITLE_RE.search(html) or ["", ""])[1])
    if not title or title in _GENERIC_TITLES:  # 寬宏 <title> 是通用字(JS渲染),跳過
        return None
    start = _extract_start(html)
    venue = _extract_venue(html)
    city = detect_city(venue)
    url = f"{base}/application/UTK02/UTK0201_.aspx?PRODUCT_ID={pid}"
    return {
        "source_name": site,
        "title": title,
        "organizer": None,
        "category": None,
        "description_clean": "",
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
    cap = cfg.get("max_detail_per_site", 50)
    today = date.today()
    horizon = today + timedelta(days=90)
    out: list[dict] = []

    for site in cfg.get("sites", []):
        name, base = site.get("name"), site.get("base")
        if not base:
            continue
        try:
            r = requests.get(
                f"{base}/application/UTK01/UTK0101_.aspx", headers=HEADERS, timeout=TIMEOUT
            )
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001
            print(f"  [era_kham] {name} listing FAIL: {e}")
            continue
        pids = list(dict.fromkeys(_PID_RE.findall(r.text)))[:cap]
        n = 0
        for pid in pids:
            time.sleep(1)  # 慢爬
            try:
                d = requests.get(
                    f"{base}/application/UTK02/UTK0201_.aspx?PRODUCT_ID={pid}",
                    headers=HEADERS, timeout=TIMEOUT,
                )
                d.raise_for_status()
                ev = _detail_to_event(name, base, pid, d.text)
            except Exception as e:  # noqa: BLE001
                print(f"  [era_kham] {name} {pid} FAIL: {e}")
                continue
            if not ev or ev["city"] not in TARGET_CITIES:
                continue
            # 時窗
            first = ev["performances"][0]["start_time"]
            if first:
                try:
                    dd = datetime.fromisoformat(first).date()
                    if dd < today or dd > horizon:
                        continue
                except ValueError:
                    pass
            out.append(ev)
            n += 1
        print(f"  [era_kham] {name} -> {n} events ({len(pids)} 檢視)")
    return out
