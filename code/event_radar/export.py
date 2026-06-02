"""把收藏清單匯出成可分享的 Markdown / 自包 HTML(含購票連結)。

Streamlit 的下載鈕 + CLI 都用這裡:
  python -m event_radar.export --html ~/my_events.html   # 產可分享 HTML
  python -m event_radar.export --md                       # 印 markdown
"""
from __future__ import annotations

import argparse
import html as _html
import json

from . import db


def liked_events(actions: tuple[str, ...] = ("want", "maybe")) -> list[dict]:
    """回傳被標記 want/maybe 的活動(含場館/連結),依日期排序。"""
    ph = ",".join("?" for _ in actions)
    with db.connect() as conn:
        rows = conn.execute(
            f"""SELECT e.*,
                   (SELECT venue_name FROM performances WHERE event_id=e.event_id
                    ORDER BY start_time LIMIT 1) AS venue,
                   (SELECT GROUP_CONCAT(DISTINCT action) FROM feedback
                    WHERE event_id=e.event_id) AS marks
                FROM events e
                WHERE e.event_id IN (
                    SELECT DISTINCT event_id FROM feedback WHERE action IN ({ph})
                )
                ORDER BY e.first_start ASC""",
            actions,
        ).fetchall()
    out = []
    for r in rows:
        marks = set((r["marks"] or "").split(","))
        # block / not_interested 蓋過 want(若同時存在,視為已取消)
        if "block_similar" in marks or "not_interested" in marks:
            continue
        out.append(
            {
                "title": r["title"],
                "date": (r["first_start"] or "")[:16].replace("T", " "),
                "n_perf": r["n_performances"] or 0,
                "city": r["city"] or "",
                "venue": r["venue"] or "",
                "score": r["personal_match_score"]
                if r["personal_match_score"] is not None
                else r["base_score"],
                "why": r["why_recommended"] or "",
                "url": r["ticket_url"] or r["source_url"] or "",
                "source": r["source_name"] or "",
                "want": "want" in marks,
            }
        )
    return out


def to_markdown(events: list[dict]) -> str:
    if not events:
        return "# 我的活動清單\n\n(還沒有收藏的活動)\n"
    lines = ["# 我的活動清單 🎫", ""]
    for e in events:
        star = "⭐" if e["want"] else "🤔"
        perf = f"（共 {e['n_perf']} 場）" if e["n_perf"] > 1 else ""
        lines.append(f"## {star} {e['title']}")
        loc = " · ".join(x for x in (e["city"], e["venue"]) if x)
        lines.append(f"- 🗓 {e['date']} {perf}".rstrip())
        if loc:
            lines.append(f"- 📍 {loc}")
        if e["url"]:
            lines.append(f"- 🔗 [購票/詳情]({e['url']})")
        if e["why"]:
            lines.append(f"- 💡 {e['why']}")
        lines.append("")
    return "\n".join(lines)


def to_html(events: list[dict], title: str = "我的活動清單") -> str:
    """自包單檔 HTML,可直接傳給朋友開(離線、含可點連結)。"""
    esc = _html.escape
    cards = []
    for e in events:
        star = "⭐" if e["want"] else "🤔"
        perf = f"（共 {e['n_perf']} 場）" if e["n_perf"] > 1 else ""
        loc = " · ".join(x for x in (e["city"], e["venue"]) if x)
        link = (
            f'<a href="{esc(e["url"])}" target="_blank">購票 / 詳情 →</a>'
            if e["url"]
            else ""
        )
        why = f'<p class="why">{esc(e["why"])}</p>' if e["why"] else ""
        cards.append(
            f"""<div class="card">
      <h2>{star} {esc(e['title'])}</h2>
      <p class="meta">🗓 {esc(e['date'])} {esc(perf)} &nbsp;·&nbsp; 📍 {esc(loc)} &nbsp;·&nbsp; 🏷 {esc(e['source'])}</p>
      {why}
      <p class="link">{link}</p>
    </div>"""
        )
    body = "\n".join(cards) if cards else "<p>(還沒有收藏的活動)</p>"
    return f"""<!doctype html>
<html lang="zh-Hant"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>
  body{{font-family:-apple-system,"Noto Sans TC",Segoe UI,sans-serif;max-width:760px;
       margin:0 auto;padding:24px;background:#faf9f7;color:#222;line-height:1.55}}
  h1{{font-size:1.6rem}}
  .sub{{color:#888;font-size:.9rem;margin-top:-8px}}
  .card{{background:#fff;border:1px solid #e7e3dc;border-radius:12px;padding:16px 18px;margin:14px 0;
         box-shadow:0 1px 3px rgba(0,0,0,.04)}}
  .card h2{{font-size:1.12rem;margin:0 0 6px}}
  .meta{{color:#666;font-size:.86rem;margin:2px 0}}
  .why{{color:#444;font-size:.95rem;margin:8px 0}}
  .link a{{display:inline-block;margin-top:6px;color:#fff;background:#c0392b;text-decoration:none;
           padding:6px 14px;border-radius:8px;font-size:.9rem}}
</style></head>
<body>
  <h1>🎫 {esc(title)}</h1>
  <p class="sub">{len(events)} 個活動 · 由 Event Radar 整理</p>
  {body}
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser(description="匯出收藏清單(含連結)")
    ap.add_argument("--html", metavar="PATH", help="寫出自包 HTML 到此路徑")
    ap.add_argument("--md", action="store_true", help="印出 markdown")
    ap.add_argument("--include-maybe", action="store_true", help="也含『也許』(預設只 want)")
    args = ap.parse_args()
    actions = ("want", "maybe") if args.include_maybe else ("want",)
    evs = liked_events(actions)
    if args.html:
        with open(args.html, "w", encoding="utf-8") as f:
            f.write(to_html(evs))
        print(f"寫出 {len(evs)} 筆 → {args.html}")
    else:
        print(to_markdown(evs))


if __name__ == "__main__":
    main()
