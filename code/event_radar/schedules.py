"""Source-verified sessions where a feed only exposes an outer date span.

Correct the public snapshot, including cached rows, without rewriting the source
database or changing favorite IDs. Never infer recurrence from first/last dates.
"""
from __future__ import annotations

from datetime import date, datetime
from urllib.parse import urlsplit

from .config import load_yaml


def source_key(value: str) -> str:
    url = urlsplit(value)
    return f"{url.netloc.lower()}{url.path.rstrip('/')}"


def reviewed_schedules() -> dict[str, dict]:
    result = {}
    for item in load_yaml("schedules.yaml").get("schedules", []):
        url = urlsplit(item["source_url"])
        key = source_key(item["source_url"])
        if url.scheme != "https" or not url.netloc or key in result:
            raise ValueError("schedule needs a unique HTTPS source")
        date.fromisoformat(item["checked_on"])
        sessions = item.get("performances", [])
        if not sessions:
            raise ValueError("reviewed schedule must have explicit sessions")
        seen = set()
        for perf in sessions:
            start = datetime.fromisoformat(perf["start_time"])
            end = datetime.fromisoformat(perf.get("end_time") or perf["start_time"])
            identity = (perf["start_time"], perf.get("venue_name", ""))
            if end < start or identity in seen:
                raise ValueError("invalid or duplicate reviewed session")
            if len(perf["start_time"]) == 10 and len(perf.get("end_time") or perf["start_time"]) != 10:
                raise ValueError("date-only session needs a date-only end")
            seen.add(identity)
        result[key] = item
    return result


def with_reviewed_schedule(event: dict, schedules: dict[str, dict]) -> dict:
    review = next((schedules[source_key(event[key])] for key in ("source_url", "ticket_url")
                   if event.get(key) and source_key(event[key]) in schedules), None)
    if not review:
        return event
    # Inherit venue/price fields, never the feed's outer start/end span.
    template = (event.get("performances") or [{}])[0]
    sessions = sorted([
        {**template, **perf, "end_time": perf.get("end_time") or perf["start_time"]}
        for perf in review["performances"]
    ], key=lambda perf: perf["start_time"])
    return {**event, "performances": sessions, "first_start": sessions[0]["start_time"],
            "_schedule_checked_on": review["checked_on"]}
