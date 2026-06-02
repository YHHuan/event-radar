"""收集 → 標準化 → dedupe → 規則 → 存 DB。CLI: python -m event_radar.pipeline"""
from __future__ import annotations

import argparse

from . import db
from .collectors import COLLECTORS
from .dedupe import dedupe_key, perf_key
from .rules import score_event


def run(only: list[str] | None = None) -> dict:
    db.init_db()
    stats = {"collected": 0, "stored": 0, "drop": 0, "demote": 0, "keep": 0, "errors": []}

    raw: list[dict] = []
    for name, fn in COLLECTORS.items():
        if only and name not in only:
            continue
        try:
            evs = fn()
            raw.extend(evs)
            print(f"[{name}] collected {len(evs)}")
        except Exception as e:  # noqa: BLE001
            print(f"[{name}] ERROR: {e}")
            stats["errors"].append(f"{name}: {e}")
    stats["collected"] = len(raw)

    with db.connect() as conn:
        for ev in raw:
            try:  # per-event fail-soft:單筆壞掉不拖垮整批
                first = _earliest(ev)
                city = ev.get("city") or _first_city(ev)
                ev["city"] = city
                n_perf = len(ev.get("performances", []))
                ev["dedupe_key"] = dedupe_key(ev.get("title", ""), first, city, n_perf)
                ev["first_start"] = first
                for pf in ev.get("performances", []):
                    pf["perf_key"] = perf_key(pf.get("start_time"), pf.get("venue_name"))
                score_event(ev)
                stats[ev["rule_decision"]] = stats.get(ev["rule_decision"], 0) + 1
                db.upsert_event(conn, ev)
                stats["stored"] += 1
            except Exception as e:  # noqa: BLE001
                stats["errors"].append(f"event '{ev.get('title','?')[:30]}': {e}")
    return stats


def _earliest(ev: dict) -> str | None:
    starts = sorted(
        p["start_time"] for p in ev.get("performances", []) if p.get("start_time")
    )
    return starts[0] if starts else None


def _first_city(ev: dict) -> str | None:
    return next(
        (p["city"] for p in ev.get("performances", []) if p.get("city")),
        None,
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Event Radar collector pipeline")
    ap.add_argument("--only", nargs="*", help="只跑指定 collector (e.g. culture_tw)")
    args = ap.parse_args()
    stats = run(only=args.only)
    print("\n=== pipeline done ===")
    for k, v in stats.items():
        print(f"  {k}: {v}")


if __name__ == "__main__":
    main()
