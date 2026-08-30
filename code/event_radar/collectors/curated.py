"""Small public, human-verified source for gaps in automatic discovery."""
from __future__ import annotations

from ..config import load_yaml


def collect() -> list[dict]:
    out: list[dict] = []
    for item in load_yaml("curated_events.yaml").get("events", []):
        start = item.get("start_time")
        venue = item.get("venue") or ""
        city = item.get("city")
        out.append(
            {
                "source_name": "Event Radar 精選",
                "title": item.get("title") or "",
                "organizer": item.get("organizer") or "",
                "category": item.get("category"),
                "description_clean": item.get("description") or "",
                "source_url": item.get("source_url"),
                "ticket_url": item.get("source_url"),
                "image_url": item.get("image_url") or None,
                "city": city,
                "tags": item.get("tags") or [],
                "performances": [
                    {
                        "start_time": start,
                        "end_time": item.get("end_time"),
                        "venue_name": venue,
                        "venue_address": venue,
                        "latitude": None,
                        "longitude": None,
                        "city": city,
                        "price_text": item.get("price"),
                        "is_ticketed": 0 if "免費" in (item.get("price") or "") else 1,
                        "availability_text": None,
                    }
                ],
            }
        )
    return out
