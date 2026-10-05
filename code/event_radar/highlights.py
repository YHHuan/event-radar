"""Reviewed public selections and undated annual interests.

The catalog is authoritative for these listings, including corrections to old
collector rows. Undated interests never become performances or calendar events.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlparse

from .config import load_yaml

LENSES = {"music_festival": "音樂祭", "folk": "民俗祭典", "endurance": "路跑三鐵"}


def validate_catalog(catalog: dict) -> None:
    seen = set()
    for group in ("events", "watchlist"):
        for item in catalog.get(group, []):
            required = ("id", "title", "lens", "source_url", "checked_on", "selection_reason")
            if any(not item.get(key) for key in required):
                raise ValueError("selection is missing required provenance or reason")
            if item["id"] in seen or item["lens"] not in LENSES:
                raise ValueError("duplicate selection id or unknown lens")
            seen.add(item["id"])
            url = urlparse(item["source_url"])
            if url.scheme != "https" or not url.netloc:
                raise ValueError("selection needs an HTTPS source")
            date.fromisoformat(item["checked_on"])
            if group == "watchlist":
                if item.get("start_time") or item.get("end_time"):
                    raise ValueError("undated watchlist must not contain calendar dates")
                continue
            start = datetime.fromisoformat(item["start_time"])
            end = datetime.fromisoformat(item.get("end_time") or item["start_time"])
            if end < start or not item.get("city") or not item.get("venue"):
                raise ValueError("selection needs a valid date range, city and venue")
            if len(item["start_time"]) == 10 and len(item.get("end_time") or item["start_time"]) != 10:
                raise ValueError("date-only selection needs a date-only end")


def catalog() -> dict:
    data = load_yaml("highlights.yaml")
    validate_catalog(data)
    return data


def selected_events() -> list[dict]:
    return [
        {
            "dedupe_key": f"selected-{item['id']}",
            "title": item["title"],
            "organizer": item.get("organizer", ""),
            "category": LENSES[item["lens"]],
            "description_clean": item["selection_reason"],
            "source_name": item.get("source_name", "主辦公開資訊"),
            "source_url": item["source_url"],
            "ticket_url": item["source_url"],
            "city": item["city"],
            "tags": item.get("tags", []),
            "first_start": item["start_time"],
            "_selection": item,
            "performances": [{
                "start_time": item["start_time"],
                "end_time": item.get("end_time") or item["start_time"],
                "venue_name": item["venue"],
                "venue_address": item.get("address", item["venue"]),
                "city": item["city"],
                "price_text": item.get("price", "依主辦公告"),
                "availability_text": item.get("registration_note", ""),
            }],
        }
        for item in catalog().get("events", [])
    ]


def public_watchlist() -> list[dict]:
    return [{
        "id": item["id"], "title": item["title"],
        "lens": item["lens"], "city": item.get("city", ""),
        "url": item["source_url"], "reason": item["selection_reason"],
        "checkedOn": item["checked_on"],
        "status": "下一屆日期待確認",
    } for item in catalog().get("watchlist", [])]
