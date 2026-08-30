# 🎫 Event Radar

Public browser: **https://yhhuan.github.io/event-radar/**

`有空` is the mobile-first, read-only view of this repository. It searches
upcoming public listings, filters by date, city and experiential lens, and keeps
saves/hides in the browser's local storage. The ranking distinguishes the event
category from why it may be worth leaving home for: live presence, curatorial
context, place, limited context, scene culture, wandering, participation and
urban nature.

> A personal, taste-based event radar for Taipei's arts / indie / niche scene.
> 個人化藝文活動雷達 —— 把分散在各售票平台的活動,自動收進來、依你的口味打分,只顯示「你可能會想去」的。

Finding good indie gigs, fringe theatre, stand-up, city walks, markets or weird-cool
experiences in Taipei means checking a dozen ticketing sites one by one. **Event Radar**
crawls them for you, keeps the next 90 days, and surfaces what matches *your* taste.

- **Aggregates 8 automatic sources plus a small verified public supplement** into one local database
- **Explainable taste ranking**: categories answer what an event is; capped experiential facets explain why it may fit
- **Two front ends**: the local Streamlit workbench and the mobile-first static `有空` browser
- **Credit-card presale tags** (e.g. `💳Mastercard`, `💳玉山`) so you can filter to events your card gets early access to
- **Local feedback stays private**: GitHub Pages receives public event metadata only; saves/hides stay in that browser

---

## How it works

```
sources.yaml ─▶ collectors ─▶ normalize ─▶ dedupe ─▶ taste facets ─▶ SQLite ─┬▶ Streamlit
                (公開來源)       標準化       去重       可解釋排序              └▶ static Pages
```

1. **Collect** — each source has an independent, fail-soft collector.
2. **Normalize & dedupe** — title/date/city cleanup; multi-show productions merge into one card (date-stable key).
3. **Taste facets** — score each experiential signal once, then combine relevance, region, timing, completeness and noise controls.
4. **Score (optional)** — a semantic score is blended only while fresh; expired model output never switches the whole result set into a stale mode.
5. **Browse** — Streamlit reads the DB live; GitHub Pages reads a bounded public snapshot.

### Discovery methodology (reusable)
Most ticketing sites are JS-rendered, but two patterns cover almost everything:
- **Structured feed / API** — e.g. the Ministry of Culture open-data JSON; KKTIX organizer `events.json`.
- **SSR listing → JSON-LD detail** — find event URLs on a server-rendered listing/search page, then parse each event page's `schema.org/Event` JSON-LD. This single approach powers the OPENTIX, Accupass, iNDIEVOX, tixcraft and Eventbrite collectors.

---

## Sources

| Source | What it covers | Method |
|---|---|---|
| 文化部 iCulture | Official arts/music/theatre/dance/exhibits | Open-data JSON API |
| OPENTIX (兩廳院) | Formal theatre, dance, musicals, film festivals | SSR listing → JSON-LD |
| KKTIX | Indie music, comedy, international concerts | Organizer `*.kktix.cc/events.json` |
| iNDIEVOX | Independent music / post-rock / livehouse | SSR listing |
| 拓元 tixcraft | International concerts, big expos | SSR listing |
| 年代售票 | Large concerts | listing → detail |
| Accupass | Markets, real-life library, city walks, food/workshops | SSR search by keyword → JSON-LD |
| Eventbrite | International / community / niche | SSR listing → JSON-LD |
| Event Radar 精選 | Small, user-supplied gaps with verified public dates | Reviewed YAML + public source URL |

> **Facebook is not supported** — events are behind a login wall and Meta's API only exposes them to Marketing Partners. In practice most FB-promoted events are cross-posted to the platforms above.

---

## Quick start

```bash
# 1. set up the environment (uv recommended; falls back to venv+pip)
bash setup.sh

# 2. collect + rule-filter into data/events.db
PYTHONPATH=code .venv/bin/python -m event_radar.pipeline          # all sources
PYTHONPATH=code .venv/bin/python -m event_radar.pipeline --only culture_tw opentix

# 3. open the front-end (idempotent: opens browser; starts server if needed)
bash run.sh        # → http://localhost:8501
```

Build the same static artifact used by GitHub Pages:

```bash
npm ci
PYTHONPATH=code .venv/bin/python -m event_radar.pipeline --only curated
npm run build
npm run check
npm run smoke
```

The scheduled Pages workflow runs without paid model APIs. The local SQLite
database is authoritative; `_site/events.json` is a derived public snapshot and
contains only public event metadata. Ticket availability and final schedules
remain authoritative on the linked organizer page.

On Windows + WSL you can drop a one-line `.bat` on your Desktop to double-click:
```bat
@echo off
wsl.exe -e bash -lc "cd ~/research/event-radar && bash run.sh"
```

### Optional: LLM scoring
The rule layer ranks by `base_score`. For taste-aware ordering, run the LLM pass:
```bash
PYTHONPATH=code .venv/bin/python -m event_radar.scoring export   # → data/unscored.json
#   feed prompts/score_prompt.md + unscored.json to your LLM, save data/scored.json
PYTHONPATH=code .venv/bin/python -m event_radar.scoring apply    # write scores back
```

---

## Configuration

- **`config/profile.yaml`** — your taste: positive/negative keywords, regions, weights, and `credit_cards.mine`. This is what makes recommendations *yours*; edit it freely.
- **`config/taste.yaml`** — the current experience facets, observed examples and model-score freshness policy.
- **`config/curated_events.yaml`** — a small reviewed supplement for public events missed by automatic discovery.
- **`config/sources.yaml`** — which sources are enabled, KKTIX organizer slugs, Accupass search keywords, etc.

---

## Project layout

```
code/event_radar/
  config.py        paths & config loading (all relative, no hardcoded paths)
  db.py            SQLite schema + atomic upsert + dedupe-key migration
  normalize.py     text / date / city normalization
  dedupe.py        cross-source dedupe key
  cards.py         credit-card presale detection
  rules.py         hard rules → base_score + keep/demote/drop
  collectors/      one module per source (fail-soft, independent)
  pipeline.py      collect → normalize → dedupe → rules → DB
  scoring.py       LLM scoring harness (export / apply)
  export.py        export saved list to shareable HTML / Markdown
code/app/          Streamlit front-end
prompts/           LLM scoring prompt
data/              SQLite DB (git-ignored, never leaves your machine)
```

## Tech
Python 3.12 · SQLite · Streamlit · `requests` + stdlib HTML/JSON-LD parsing (no heavyweight scraping deps).

## Notes & limitations
- Collectors crawl public pages politely (≤1 req/sec, identifying User-Agent). Respect each site's ToS.
- Some sources are Cloudflare- or JS-gated; those are handled via organizer feeds / structured data, or left out.
- This is a personal project shared as-is.

## License
MIT — see [LICENSE](LICENSE).
