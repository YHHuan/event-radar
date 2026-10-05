# 🎫 Event Radar

Public browser: **https://yhhuan.github.io/event-radar/**

`有空` is the mobile-first, read-only view of this repository. It searches
upcoming public listings, filters by date, city and experiential lens, and keeps
saves/hides in the browser's local storage. The ranking distinguishes the event
category from why it may be worth leaving home for: live presence, curatorial
context, place, limited context, scene culture, wandering, participation and
urban nature.

The **音樂祭 / 民俗祭典 / 路跑三鐵** shortcuts show Taiwan-wide selections,
including announced events up to a year ahead. Races are selected for their scale,
distinctive route or local culture; merely mentioning a marathon does not qualify.
Multi-day events remain visible until their last day. **年度追蹤** holds undated
interests such as Yanshui and Mazu pilgrimages separately from the calendar.

> A personal, taste-based event radar for Taipei's arts / indie / niche scene.
> 個人化藝文活動雷達 —— 把分散在各售票平台的活動,自動收進來、依你的口味打分,只顯示「你可能會想去」的。

Finding good indie gigs, fringe theatre, stand-up, city walks, markets or weird-cool
experiences in Taipei means checking a dozen ticketing sites one by one. **Event Radar**
crawls them for you, keeps the next 90 days, and surfaces what matches *your* taste.

- **Aggregates ticketing platforms, government calendars and organizer feeds**, with reviewed date corrections
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
| 觀光署 | Taiwan folk events and music festivals | Daily v2 event JSON ZIP |
| 超馬協會 | Domestic ultra, overnight, trail and relay races | Official calendar table, explicit edition years |
| Focusline | CRUFU, trail, 100K and distinctive triathlon races | Public activity API; race and registration dates separated |
| Festival organizers | 浮現、光球、PIPE、浪人祭、高流 | Public KKTIX organizer feeds; festival titles only |
| Event Radar 精選 | Small, user-supplied gaps with verified public dates | Reviewed YAML + public source URL |

The **活動情報站** directory is maintained in `config/discovery.yaml`. Its eight
automatic endpoints run in the existing daily refresh. Religion calendars,
organizer sites, official Facebook pages and media indexes are labeled **人工追蹤**;
they are discovery windows, not claimed social-media integrations.

Discovery snapshots live in `discovery_snapshots` in the existing SQLite database.
Successful refreshes replace a source's previous set, including an empty future
calendar. Failures keep the last success for at most seven days and show the failure
and last successful date publicly. Historical DB rows cannot restore an expired
managed feed. A zero count can mean the next festival has not yet been announced.

Reviewed entries in `config/highlights.yaml` override matching feed titles and
edition years (or explicit `supersedes_titles`). For example, the Zuoying
district announcement corrects an outdated national-calendar range. Unknown dates,
cancelled/postponed listings, long seasonal spans without individual dates, and
suspicious shifted all-day timestamps are excluded from automatic discovery.
Date-only listings never acquire invented start times. The tourism TLS adapter
retains certificate-chain and hostname checks while allowing that host's legacy
CA extensions on Python 3.13+; other hosts keep the default TLS behavior.

Races require an explicit distinctive signal from a selected organizer or a reviewed
selection. General 5K listings and training/volunteer courses do not qualify.
The folk lens also requires a selection, so a permanent exhibit merely mentioning
pilgrimages is not presented as a current ritual or festival.
Shared organizer calendars carry `sharedSourceUrl`, so a disappearing saved race
cannot be replaced by another race merely because they share a calendar URL.

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
PYTHONPATH=code .venv/bin/python -m event_radar.pipeline --only curated discovery
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
- **`config/highlights.yaml`** — sourced festival/race selections and undated annual interests. Each entry has an explicit reason and check date. Reviewed values override stale collector rows with the same source URL; normal listings keep the 120-day window while these selections can extend to 365 days.
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
- Festival organizer feeds refresh on the existing daily workflow. The reviewed
  race/folk catalog and annual watchlist require checking official announcements;
  the site's build timestamp is not a new manual verification date. Do not infer
  next year's lunar dates. Add confirmed dates to `events`, keep unconfirmed
  editions in `watchlist`, and record signup status separately from event dates.
- Date-only selections export as all-day calendar entries with an exclusive end
  date. Timed entries use Asia/Taipei. Browser favorites retain these details.

## License
MIT — see [LICENSE](LICENSE).
