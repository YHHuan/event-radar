"""Source directory and replaceable discovery snapshots in the existing database.

Unlike historical event rows, a successful feed refresh replaces its prior set.
Failures retain at most seven days of data and expose freshness to the reader.
"""
from __future__ import annotations

import json
import copy
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlparse

from . import db
from .config import load_yaml

SCHEMA = """CREATE TABLE IF NOT EXISTS discovery_snapshots (
    source_id TEXT PRIMARY KEY, checked_at TEXT NOT NULL,
    succeeded_at TEXT, status TEXT NOT NULL, events_json TEXT NOT NULL DEFAULT '[]'
)"""


def record_result(source_id: str, events: list[dict] | None, *, now: datetime | None = None) -> None:
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")
    with db.connect() as conn:
        conn.execute(SCHEMA)
        conn.execute("""INSERT INTO discovery_snapshots
            (source_id, checked_at, succeeded_at, status, events_json) VALUES (?,?,?,?,?)
            ON CONFLICT(source_id) DO UPDATE SET checked_at=excluded.checked_at,
                status=excluded.status,
                succeeded_at=COALESCE(excluded.succeeded_at, discovery_snapshots.succeeded_at),
                events_json=CASE WHEN excluded.status='ok' THEN excluded.events_json
                           ELSE discovery_snapshots.events_json END""",
                     (source_id, stamp, stamp if events is not None else None,
                      "ok" if events is not None else "error",
                      json.dumps(events or [], ensure_ascii=False)))


def _records() -> dict:
    with db.connect() as conn:
        # Reads/builds do not create or migrate source state.
        if not conn.execute("SELECT name FROM sqlite_master WHERE name='discovery_snapshots'").fetchone():
            return {}
        return {row["source_id"]: dict(row) for row in conn.execute("SELECT * FROM discovery_snapshots")}


def _fresh(row: dict, today: date) -> bool:
    return bool(row.get("succeeded_at") and
                today - timedelta(days=7) <= date.fromisoformat(row["succeeded_at"][:10]) <= today)


def cached_events(*, today: date | None = None) -> list[dict]:
    today = today or date.today()
    records = _records()
    out = []
    for source in load_yaml("discovery.yaml").get("sources", []):
        row = records.get(source["id"], {})
        if source.get("mode") != "automatic" or not _fresh(row, today):
            continue
        for event in json.loads(row["events_json"]):
            event["_selection"]["checked_on"] = row["succeeded_at"][:10]
            event["_selection"]["source_id"] = source["id"]
            out.append(event)
    return merge_music_catalogs(out)


def merge_music_catalogs(events: list[dict]) -> list[dict]:
    """Coalesce matching ticket pages, retaining every explicit session.

    Generic calendars and social profile links are not event identifiers. For
    those, only the same series title (optionally ending in an occurrence date)
    and city can merge. Existing reviewed selections are untouched.
    """
    def base_title(event):
        title = re.sub(r"\s*[-－—｜|]?\s*\d{1,2}/\d{1,2}\s*$", "", event["title"])
        return re.sub(r"[\W_]+", "", title).replace("臺", "台").casefold()

    def ticket_key(event):
        url = event.get("ticket_url") or ""
        parsed = urlparse(url)
        if re.search(r"/(?:activity/detail|events|event|gigs)/[\w-]+/?$", parsed.path):
            return (parsed.hostname or "").removeprefix("www.") + parsed.path.rstrip("/")
        return ""

    def same_venue(a, b):
        def key(value):
            return re.sub(r"[\W_]+", "", re.split(r"[（(]", value or "")[0]).casefold()
        left, right = key(a.get("venue_name")), key(b.get("venue_name"))
        return bool(left and right and (left in right or right in left))

    out = []
    for original in events:
        item = copy.deepcopy(original)
        if not item.get("_selection", {}).get("catalog"):
            out.append(item)
            continue
        match = next((other for other in out if other.get("_selection", {}).get("catalog") and
                      ((ticket_key(item) and ticket_key(other) == ticket_key(item)) or
                       (base_title(other) == base_title(item) and other.get("city") == item.get("city")))), None)
        if match is None:
            out.append(item)
            continue
        perfs = match["performances"]
        for perf in item["performances"]:
            # Community listings sometimes use admission time while the ticket
            # page uses show time. A discrepancy is not an additional show.
            official = (match.get("source_name") in {"iNDIEVOX", "FANSI GO"}
                        and item.get("source_name") == "StreetVoice 街聲"
                        and ((ticket_key(match) == ticket_key(item) and ticket_key(item))
                             or (base_title(match) == base_title(item)
                                 and any(same_venue(p, perf) for p in perfs))))
            authoritative = [p for p in perfs if p["start_time"][:10] == perf["start_time"][:10]
                             and p.get("city") == perf.get("city")] if official else []
            if authoritative and all(len(p["start_time"]) > 10 for p in authoritative):
                if not any(p["start_time"] == perf["start_time"] for p in authoritative):
                    match["_selection"]["registration_note"] = "來源時間有差異；此卡依售票頁，出發前請再確認。"
                continue
            same = next((p for p in perfs if p["start_time"][:10] == perf["start_time"][:10]
                         and p.get("city") == perf.get("city")
                         and same_venue(p, perf)
                         and (p["start_time"] == perf["start_time"] or
                              len(p["start_time"]) == 10 or len(perf["start_time"]) == 10)), None)
            if same is None:
                perfs.append(perf)
            else:
                if len(same["start_time"]) == 10 and len(perf["start_time"]) > 10:
                    same["start_time"] = perf["start_time"]
                for key in ("end_time", "venue_name", "venue_address", "price_text"):
                    same[key] = same.get(key) or perf.get(key)
        perfs.sort(key=lambda p: (p["start_time"], p["venue_name"]))
        match["first_start"] = perfs[0]["start_time"]
        # A separate daily card should not label the merged series as day one.
        match["title"] = re.sub(r"\s*[-－—｜|]?\s*\d{1,2}/\d{1,2}\s*$", "", match["title"])
    return out


def public_sources(*, today: date | None = None) -> list[dict]:
    today = today or date.today()
    records = _records()
    out = []
    for source in load_yaml("discovery.yaml").get("sources", []):
        row = records.get(source["id"], {})
        automatic = source.get("mode") == "automatic"
        fresh = _fresh(row, today)
        status = ("人工追蹤" if not automatic else "尚未更新" if not row else
                  "更新失敗，保留近期資料" if row["status"] == "error" and fresh else
                  "更新失敗，等待恢復" if row["status"] == "error" else
                  "資料已過期" if not fresh else "每日更新")
        events = json.loads(row.get("events_json", "[]")) if fresh else []
        upcoming = sum(any((p.get("end_time") or p.get("start_time") or "")[:10] >= today.isoformat()
                           for p in e.get("performances", [])) for e in events)
        out.append({"id": source["id"], "name": source["name"], "url": source["url"],
                    "lenses": source["lenses"], "mode": source["mode"], "status": status,
                    "note": source["note"], "checkedAt": row.get("checked_at", ""),
                    "lastSuccess": row.get("succeeded_at") or "", "count": upcoming})
    return out


def managed_source_names() -> set[str]:
    return {item["name"] for item in load_yaml("discovery.yaml").get("sources", [])
            if item.get("mode") == "automatic"}
