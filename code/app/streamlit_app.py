"""Event Radar 前台。 run: streamlit run code/app/streamlit_app.py
分層:Discover / This Month / Next 90 / Maybe / Saved / 匯出分享 / 已隱藏 / Sources。
排序:有 Claude personal_match_score 用它,沒有就退回 base_score。
標記為單一狀態 toggle(再點一次取消);want/maybe 進收藏,not_interested/block 進已隱藏。"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

import streamlit as st

# 讓 app 找得到 event_radar 套件 (code/ 在 sys.path)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from event_radar.cards import my_cards  # noqa: E402
from event_radar.config import DB_PATH, profile  # noqa: E402
from event_radar.db import init_db, now_iso  # noqa: E402
from event_radar.export import liked_events, to_html, to_markdown  # noqa: E402

_MY_CARDS = set(my_cards())
ONLY_MY_CARD = False  # 由 sidebar 勾選覆寫

st.set_page_config(page_title="Event Radar", page_icon="🎫", layout="wide")
P = profile()
TIERS = P.get("tiers", {"discover_min": 80, "maybe_min": 50})

_STATE_LABEL = {
    "want": "想去 ⭐", "maybe": "也許 🤔",
    "not_interested": "不感興趣 🙅", "block_similar": "別再看到類似 🚫",
}


def conn():
    init_db()
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def effective_score(r) -> int:
    return r["personal_match_score"] if r["personal_match_score"] is not None else r["base_score"] or 0


def feedback_state() -> dict[int, str]:
    """event_id -> 目前單一標記狀態(取最新一筆)。"""
    c = conn()
    rows = c.execute(
        "SELECT event_id, action FROM feedback ORDER BY created_at"
    ).fetchall()
    c.close()
    state: dict[int, str] = {}
    for r in rows:
        state[r["event_id"]] = r["action"]  # 後面的覆蓋前面 → 最新
    return state


def toggle_feedback(event_id: int, action: str):
    """單一狀態 toggle:點目前狀態→清除(取消);點別的→切換。"""
    c = conn()
    cur = c.execute(
        "SELECT action FROM feedback WHERE event_id=? ORDER BY created_at DESC LIMIT 1",
        (event_id,),
    ).fetchone()
    c.execute("DELETE FROM feedback WHERE event_id=?", (event_id,))  # 先清(單一狀態)
    if not cur or cur["action"] != action:
        c.execute(
            "INSERT INTO feedback (event_id, action, created_at) VALUES (?,?,?)",
            (event_id, action, now_iso()),
        )
    c.commit()
    c.close()


def clear_feedback(event_id: int):
    c = conn()
    c.execute("DELETE FROM feedback WHERE event_id=?", (event_id,))
    c.commit()
    c.close()


def add_inbox(url: str, note: str = ""):
    c = conn()
    c.execute("INSERT INTO inbox (url, added_at, note) VALUES (?,?,?)", (url, now_iso(), note))
    c.commit()
    c.close()


def has_my_card(r) -> bool:
    tags = json.loads(r["tags"] or "[]")
    return any(t.startswith("💳") and t[1:] in _MY_CARDS for t in tags)


def fetch(where: str = "", params=(), order="ORDER BY first_start ASC", exclude_hidden=True):
    c = conn()
    rows = c.execute(
        f"""SELECT * FROM events
            WHERE rule_decision != 'drop' AND status='active' {where} {order}""",
        params,
    ).fetchall()
    c.close()
    if exclude_hidden:
        hidden = {e for e, a in feedback_state().items() if a in ("not_interested", "block_similar")}
        rows = [r for r in rows if r["event_id"] not in hidden]
    if ONLY_MY_CARD:
        rows = [r for r in rows if has_my_card(r)]
    return rows


def card(r, ctx="", state: dict | None = None):
    state = state if state is not None else feedback_state()
    cur = state.get(r["event_id"])
    score = effective_score(r)
    tags = json.loads(r["tags"] or "[]")
    with st.container(border=True):
        cols = st.columns([1, 5, 2])
        if r["image_url"]:
            cols[0].image(r["image_url"], width="stretch")
        with cols[1]:
            badge = f"  ·  {_STATE_LABEL[cur]} ✓" if cur else ""
            st.markdown(f"**[{score}] {r['title']}**{badge}")
            when = r["first_start"] or "?"
            extra = f"（共 {r['n_performances']} 場）" if (r["n_performances"] or 0) > 1 else ""
            st.caption(f"🗓 {when[:16].replace('T',' ')} {extra} · 📍 {r['city'] or '?'} · 🏷 {r['source_name']}")
            if tags:
                st.caption("· ".join(tags[:8]))
            if r["why_recommended"]:
                st.write(r["why_recommended"])
            links = []
            if r["ticket_url"]:
                links.append(f"[購票/詳情]({r['ticket_url']})")
            if r["source_url"] and r["source_url"] != r["ticket_url"]:
                links.append(f"[來源]({r['source_url']})")
            if links:
                st.markdown(" · ".join(links))
        with cols[2]:
            eid = r["event_id"]
            k = f"{ctx}_{eid}"  # 同活動可能出現在多分頁,key 要含分頁前綴
            # 標記是 toggle:目前狀態的鈕標成「取消」
            w = "⭐ 取消想去" if cur == "want" else "想去 ⭐"
            m = "🤔 取消也許" if cur == "maybe" else "也許 🤔"
            if st.button(w, key=f"w_{k}"):
                toggle_feedback(eid, "want"); st.rerun()
            if st.button(m, key=f"m_{k}"):
                toggle_feedback(eid, "maybe"); st.rerun()
            if st.button("不感興趣 🙅", key=f"n_{k}"):
                toggle_feedback(eid, "not_interested"); st.rerun()
            if st.button("別再看到類似 🚫", key=f"b_{k}"):
                toggle_feedback(eid, "block_similar"); st.rerun()


# ── sidebar ──
st.sidebar.title("🎫 Event Radar")
c = conn()
total = c.execute("SELECT COUNT(*) n FROM events").fetchone()["n"]
scored = c.execute("SELECT COUNT(*) n FROM events WHERE personal_match_score IS NOT NULL").fetchone()["n"]
c.close()
st.sidebar.caption(f"DB: {total} 活動 · {scored} 已 Claude 打分")
city_filter = st.sidebar.multiselect("城市", ["台北市", "新北市", "基隆市", "桃園市"], default=["台北市", "新北市"])
ONLY_MY_CARD = st.sidebar.checkbox(f"💳 只看有我的卡優惠 ({'/'.join(sorted(_MY_CARDS))})")

st.sidebar.markdown("---")
st.sidebar.subheader("📥 丟連結進 Inbox")
url = st.sidebar.text_input("活動連結 (KKTIX/Accupass/IG/FB...)")
if st.sidebar.button("加入") and url:
    add_inbox(url)
    st.sidebar.success("已加入 inbox(待解析)")

city_clause = ""
city_params: tuple = ()
if city_filter:
    city_clause = " AND city IN (%s)" % ",".join("?" * len(city_filter))
    city_params = tuple(city_filter)

tab = st.tabs(
    ["✨ Discover", "📅 This Month", "🗓 Next 90", "🤔 Maybe",
     "⭐ Saved", "📤 匯出/分享", "🙈 已隱藏", "⚙ Sources"]
)

with tab[0]:
    st.subheader("高分推薦")
    rows = fetch(city_clause, city_params, "ORDER BY COALESCE(personal_match_score, base_score) DESC, first_start ASC")
    hi = [r for r in rows if effective_score(r) >= TIERS["discover_min"]]
    if not hi:
        st.info("還沒有 ≥80 分的活動。先跑 Claude 打分,或看 Next 90。")
        hi = rows[:30]
    state = feedback_state()
    for r in hi[:50]:
        card(r, "discover", state)

with tab[1]:
    st.subheader("這個月")
    end = (datetime.now() + timedelta(days=31)).isoformat()
    rows = fetch(city_clause + " AND first_start <= ?", city_params + (end,), "ORDER BY first_start ASC")
    st.caption(f"{len(rows)} 場")
    state = feedback_state()
    for r in rows[:80]:
        card(r, "month", state)

with tab[2]:
    st.subheader("未來 90 天(全部 keep)")
    rows = fetch(city_clause + " AND rule_decision='keep'", city_params, "ORDER BY first_start ASC")
    st.caption(f"{len(rows)} 場")
    state = feedback_state()
    for r in rows[:150]:
        card(r, "next90", state)

with tab[3]:
    st.subheader("可能有趣 (50-79 / 規則 demote)")
    rows = fetch(city_clause, city_params, "ORDER BY COALESCE(personal_match_score, base_score) DESC")
    mid = [r for r in rows if TIERS["maybe_min"] <= effective_score(r) < TIERS["discover_min"]]
    state = feedback_state()
    for r in mid[:80]:
        card(r, "maybe", state)

with tab[4]:
    st.subheader("收藏 (想去 / 也許)")
    state = feedback_state()
    ids = [e for e, a in state.items() if a in ("want", "maybe")]
    c = conn()
    rows = [c.execute("SELECT * FROM events WHERE event_id=?", (i,)).fetchone() for i in ids]
    c.close()
    rows = [x for x in rows if x]
    rows.sort(key=lambda r: r["first_start"] or "")
    if not rows:
        st.info("還沒有收藏。在任何活動按「想去 ⭐」或「也許 🤔」就會進這裡。")
    for r in rows:
        card(r, "saved", state)

with tab[5]:
    st.subheader("📤 匯出 / 分享我的清單")
    st.caption("把收藏的活動(含購票連結)輸出成檔案,傳給朋友。HTML 可直接點開、Markdown 可貼到 LINE/Notion。")
    scope = st.radio("包含範圍", ["只『想去 ⭐』", "想去 + 也許"], horizontal=True)
    actions = ("want",) if scope.startswith("只") else ("want", "maybe")
    evs = liked_events(actions)
    st.write(f"目前清單:**{len(evs)}** 個活動")
    if evs:
        cdl = st.columns(2)
        cdl[0].download_button(
            "⬇ 下載 HTML(可直接開/分享)", to_html(evs),
            file_name="my_events.html", mime="text/html", width="stretch",
        )
        cdl[1].download_button(
            "⬇ 下載 Markdown(貼 LINE/Notion)", to_markdown(evs),
            file_name="my_events.md", mime="text/markdown", width="stretch",
        )
        st.markdown("---")
        st.caption("預覽:")
        st.markdown(to_markdown(evs))
    else:
        st.info("還沒有收藏的活動。先去 Discover 按幾個「想去 ⭐」。")

with tab[6]:
    st.subheader("🙈 已隱藏(不感興趣 / 別再看到類似)")
    st.caption("按「↩ 恢復」可讓它重新出現在推薦裡。")
    state = feedback_state()
    hidden_ids = [e for e, a in state.items() if a in ("not_interested", "block_similar")]
    c = conn()
    hrows = [c.execute("SELECT * FROM events WHERE event_id=?", (i,)).fetchone() for i in hidden_ids]
    c.close()
    hrows = [x for x in hrows if x]
    if not hrows:
        st.info("沒有已隱藏的活動。")
    for r in hrows:
        cc = st.columns([6, 1])
        cc[0].markdown(f"**{r['title']}**  ·  {_STATE_LABEL[state[r['event_id']]]}")
        if cc[1].button("↩ 恢復", key=f"restore_{r['event_id']}"):
            clear_feedback(r["event_id"]); st.rerun()

with tab[7]:
    st.subheader("來源狀態")
    from event_radar.config import CONFIG_DIR
    st.code((CONFIG_DIR / "sources.yaml").read_text(encoding="utf-8"), language="yaml")
