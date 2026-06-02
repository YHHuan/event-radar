"""Claude-in-the-loop 打分 harness。

流程 (cron 喚醒 Claude 時):
  1. python -m event_radar.scoring export   -> data/unscored.json
  2. Claude 讀 prompts/score_prompt.md + unscored.json,逐筆打分,寫 data/scored.json
  3. python -m event_radar.scoring apply     -> 寫回 events 表

只打 rule_decision != 'drop' 且尚未 scored 的活動,省 token。
"""
from __future__ import annotations

import argparse
import json

from . import db
from .config import DATA_DIR

UNSCORED = DATA_DIR / "unscored.json"
SCORED = DATA_DIR / "scored.json"


def export(limit: int = 200) -> int:
    db.init_db()
    with db.connect() as conn:
        rows = conn.execute(
            """SELECT event_id, title, organizer, category, description_clean,
                      city, tags, first_start, last_start, n_performances,
                      base_score, noise_flags, source_name
               FROM events
               WHERE rule_decision != 'drop'
                 AND personal_match_score IS NULL
               ORDER BY base_score DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
    items = [dict(r) for r in rows]
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    UNSCORED.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"exported {len(items)} unscored events -> {UNSCORED}")
    return len(items)


def apply() -> int:
    if not SCORED.exists():
        print(f"no {SCORED}; run export + Claude scoring first")
        return 0
    scored = json.loads(SCORED.read_text(encoding="utf-8"))
    n = 0
    with db.connect() as conn:
        for s in scored:
            # 對齊 score_prompt.md:category(str) + subcategories(list) + vibe_tags(list)
            merged_tags = list(dict.fromkeys(
                (s.get("vibe_tags") or []) + (s.get("subcategories") or [])
            ))
            conn.execute(
                """UPDATE events SET
                     personal_match_score=?, noise_score=?, is_recommended=?,
                     why_recommended=?, subcategory=?, score_model=?, scored_at=?,
                     tags=?
                   WHERE event_id=?""",
                (
                    s.get("personal_match_score"),
                    s.get("noise_score"),
                    1 if s.get("is_recommended") else 0,
                    s.get("why_recommended"),
                    s.get("category"),
                    s.get("score_model", "claude"),
                    db.now_iso(),
                    json.dumps(merged_tags, ensure_ascii=False),
                    s.get("event_id"),
                ),
            )
            n += 1
    print(f"applied {n} scores")
    return n


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["export", "apply"])
    ap.add_argument("--limit", type=int, default=200)
    args = ap.parse_args()
    if args.cmd == "export":
        export(args.limit)
    else:
        apply()


if __name__ == "__main__":
    main()
