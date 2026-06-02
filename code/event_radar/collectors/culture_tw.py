"""文化部 iCulture 開放資料 API collector。
端點: .../SearchShowAction.do?method=doFindTypeJ&category=<id>
回傳含 showInfo[] (場次), sourceWebPromote (售票連結), imageUrl, startDate/endDate。"""
from __future__ import annotations

import requests

from ..config import sources
from ..normalize import clean_text, detect_city, parse_dt

TIMEOUT = 25
HEADERS = {"User-Agent": "event-radar/0.1 (personal)"}


def _to_event(rec: dict) -> dict:
    title = clean_text(rec.get("title"))
    desc = clean_text(rec.get("descriptionFilterHtml") or rec.get("showInfo", [{}])[0].get("descriptionFilterHtml", "") if rec.get("showInfo") else "")
    units = rec.get("masterUnit") or rec.get("showUnit") or []
    organizer = ", ".join(units) if isinstance(units, list) else str(units)

    perfs = []
    for s in rec.get("showInfo", []) or []:
        addr = clean_text(s.get("location"))
        name = clean_text(s.get("locationName"))
        perfs.append(
            {
                "start_time": parse_dt(s.get("time")),
                "end_time": parse_dt(s.get("endTime")),
                "venue_name": name,
                "venue_address": addr,
                "latitude": _f(s.get("latitude")),
                "longitude": _f(s.get("longitude")),
                "city": detect_city(addr, name),
                "price_text": clean_text(s.get("price")),
                "is_ticketed": 1 if s.get("onSales") == "Y" else 0,
                "availability_text": s.get("onSales"),
            }
        )

    city = next((p["city"] for p in perfs if p.get("city")), None)
    return {
        "source_name": "文化部iCulture",
        "title": title,
        "organizer": organizer,
        "category": str(rec.get("category", "")),
        "description_clean": desc,
        "source_url": rec.get("sourceWebPromote") or rec.get("webSales"),
        "ticket_url": rec.get("webSales") or rec.get("sourceWebPromote"),
        "image_url": rec.get("imageUrl"),
        "city": city,
        "tags": [],
        "uid": rec.get("UID"),
        "performances": perfs,
    }


def _f(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def collect() -> list[dict]:
    cfg = sources().get("culture_tw", {})
    if not cfg.get("enabled"):
        return []
    base = cfg["base_url"]
    out: list[dict] = []
    for cat in cfg.get("categories", {}):
        url = base.format(category=cat)
        try:
            r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            r.raise_for_status()
            data = r.json()
        except Exception as e:  # noqa: BLE001 — fail-soft,單類別失敗不影響其他
            print(f"  [culture_tw] category={cat} FAIL: {e}")
            continue
        cat_events = [_to_event(rec) for rec in data if rec.get("title")]
        out.extend(cat_events)
        print(f"  [culture_tw] category={cat} -> {len(cat_events)} events")
    return out
