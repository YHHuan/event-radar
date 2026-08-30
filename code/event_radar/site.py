"""Build the public, read-only GitHub Pages snapshot."""
from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from . import db
from .config import PROJECT_ROOT, taste
from .taste import analyze_event, blended_score, normalized_image_url

WEB_DIR = PROJECT_ROOT / "web"
DEFAULT_OUTPUT = PROJECT_ROOT / "_site"
PUBLIC_URL = "https://yhhuan.github.io/event-radar/"


def _json_list(value: str | list | None) -> list:
    if isinstance(value, list):
        return value
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _safe_url(value: str | None) -> str:
    url = (value or "").strip()
    parsed = urlparse(url)
    return url if parsed.scheme in {"http", "https"} and parsed.netloc else ""


def _price(value: str | None) -> str:
    text = " ".join((value or "").split())
    if not text or len(text) > 90:
        return ""
    return text


def _load_candidates(today: date, horizon_days: int) -> list[dict]:
    db.init_db()
    start = today.isoformat()
    end = (today + timedelta(days=horizon_days + 1)).isoformat()
    with db.connect() as conn:
        event_rows = conn.execute(
            """SELECT * FROM events
               WHERE status = 'active'
                 AND first_start IS NOT NULL
                 AND first_start >= ? AND first_start < ?
               ORDER BY first_start, event_id""",
            (start, end),
        ).fetchall()
        ids = [row["event_id"] for row in event_rows]
        performances: dict[int, list[dict]] = {event_id: [] for event_id in ids}
        if ids:
            placeholders = ",".join("?" for _ in ids)
            perf_rows = conn.execute(
                f"""SELECT * FROM performances
                    WHERE event_id IN ({placeholders})
                    ORDER BY start_time""",
                ids,
            ).fetchall()
            for row in perf_rows:
                performances[row["event_id"]].append(dict(row))

    out: list[dict] = []
    for row in event_rows:
        item = dict(row)
        item["tags"] = _json_list(item.get("tags"))
        item["noise_flags"] = _json_list(item.get("noise_flags"))
        item["performances"] = performances.get(item["event_id"], [])
        out.append(item)
    return out


def snapshot(*, today: date | None = None, horizon_days: int = 120, max_events: int = 500) -> dict:
    today = today or date.today()
    cfg = taste()
    prepared: list[dict] = []
    seen: set[tuple[str, str, str]] = set()

    for event in _load_candidates(today, horizon_days):
        analysis = analyze_event(event, today=today)
        rank, rank_mode = blended_score(event, analysis)
        if analysis["decision"] == "drop" or rank < 38:
            continue

        public_url = _safe_url(event.get("ticket_url") or event.get("source_url"))
        if not public_url:
            continue
        performances = []
        for perf in event.get("performances") or []:
            start_time = perf.get("start_time")
            if not start_time or start_time[:10] < today.isoformat():
                continue
            performances.append(
                {
                    "start": start_time,
                    "end": perf.get("end_time") or "",
                    "venue": perf.get("venue_name") or "",
                    "address": perf.get("venue_address") or "",
                    "price": _price(perf.get("price_text")),
                }
            )
        if not performances:
            continue

        title = (event.get("title") or "").strip()
        city = event.get("city") or "地點待確認"
        first = performances[0]
        dedupe = ("".join(title.casefold().split()), first["start"][:10], city)
        if dedupe in seen:
            continue
        seen.add(dedupe)

        if analysis["signature_matches"] or rank >= 82:
            tier = "pick"
        elif rank >= 60:
            tier = "strong"
        else:
            tier = "explore"
        prepared.append(
            {
                "id": event.get("dedupe_key") or f"event-{event['event_id']}",
                "title": title,
                "organizer": (event.get("organizer") or "").strip(),
                "category": event.get("category") or "活動",
                "city": city,
                "source": event.get("source_name") or "公開來源",
                "url": public_url,
                "image": normalized_image_url(event.get("image_url")),
                "firstStart": first["start"],
                "lastStart": (performances[-1].get("start") or first["start"]),
                "venue": first["venue"],
                "price": first["price"],
                "performances": performances[:20],
                "performanceCount": len(performances),
                "score": rank,
                "scoreMode": rank_mode,
                "tier": tier,
                "reason": analysis["reason"],
                "facets": [
                    {"key": item["key"], "label": item["label"]}
                    for item in analysis["facets"][:4]
                ],
                "lenses": [
                    {"key": item["key"], "label": item["label"]}
                    for item in analysis["lenses"][:3]
                ],
                "confidence": analysis["confidence"],
                "tags": list(dict.fromkeys(event.get("tags") or []))[:8],
            }
        )

    prepared.sort(key=lambda event: (-event["score"], event["firstStart"], event["title"]))
    prepared = prepared[:max_events]
    source_counts = Counter(event["source"] for event in prepared)
    city_counts = Counter(event["city"] for event in prepared)
    lens_counts = Counter(
        lens["key"] for event in prepared for lens in event.get("lenses", [])
    )
    generated_at = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    return {
        "schema": "event-radar-public/v1",
        "generatedAt": generated_at,
        "today": today.isoformat(),
        "horizonDays": horizon_days,
        "tasteRevision": cfg.get("revision"),
        "publicUrl": PUBLIC_URL,
        "events": prepared,
        "meta": {
            "count": len(prepared),
            "pickCount": sum(event["tier"] == "pick" for event in prepared),
            "strongCount": sum(event["tier"] == "strong" for event in prepared),
            "sources": dict(source_counts.most_common()),
            "cities": dict(city_counts.most_common()),
            "lenses": dict(lens_counts.most_common()),
        },
    }


def _copy_assets(output: Path) -> None:
    for name in ("index.html", "app.js", "styles.css", "manifest.webmanifest"):
        shutil.copy2(WEB_DIR / name, output / name)
    icon_source = PROJECT_ROOT / "node_modules" / "lucide-static" / "icons"
    icon_output = output / "icons"
    icon_output.mkdir(exist_ok=True)
    for icon in (
        "search", "sliders-horizontal", "x", "heart", "eye-off", "external-link",
        "calendar-plus", "map-pin", "clock-3", "rotate-ccw", "share-2",
    ):
        source = icon_source / f"{icon}.svg"
        if not source.exists():
            raise FileNotFoundError(f"missing Lucide icon: {source}")
        shutil.copy2(source, icon_output / source.name)


def build(output: Path = DEFAULT_OUTPUT) -> dict:
    output.mkdir(parents=True, exist_ok=True)
    data = snapshot()
    (output / "events.json").write_text(
        json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    status = {
        "schema": "event-radar-status/v1",
        "generatedAt": data["generatedAt"],
        "tasteRevision": data["tasteRevision"],
        "counts": data["meta"],
        "coverage": {
            "firstDate": min((event["firstStart"][:10] for event in data["events"]), default=""),
            "lastDate": max((event["firstStart"][:10] for event in data["events"]), default=""),
        },
    }
    (output / "site-status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _copy_assets(output)
    (output / ".nojekyll").touch()
    return status


def check(output: Path = DEFAULT_OUTPUT, *, min_events: int = 30, min_sources: int = 2) -> dict:
    status_path = output / "site-status.json"
    if not status_path.exists():
        raise RuntimeError("site-status.json is missing; build the site first")
    status = json.loads(status_path.read_text(encoding="utf-8"))
    count = int(status.get("counts", {}).get("count", 0))
    sources = status.get("counts", {}).get("sources", {})
    if count < min_events:
        raise RuntimeError(f"public snapshot is implausibly small: {count} < {min_events}")
    if len(sources) < min_sources:
        raise RuntimeError(f"public snapshot has too few sources: {len(sources)} < {min_sources}")
    if not status.get("coverage", {}).get("lastDate"):
        raise RuntimeError("public snapshot has no future coverage")
    return status


def main() -> None:
    parser = argparse.ArgumentParser(description="Build/check the public Event Radar site")
    parser.add_argument("command", choices=("build", "check"))
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.command == "build":
        status = build(args.output)
        print(
            f"built {status['counts']['count']} events from "
            f"{len(status['counts']['sources'])} sources -> {args.output}"
        )
    else:
        status = check(args.output)
        print(
            f"health OK: {status['counts']['count']} events, "
            f"{len(status['counts']['sources'])} sources, "
            f"through {status['coverage']['lastDate']}"
        )


if __name__ == "__main__":
    main()
