# Result: Taste-aware public event radar

Upstream plan: `.ake/work/taste-aware-public-radar/plan.md`
Terminal state: succeeded

## Outcome

- Replaced unbounded broad-keyword accumulation with capped experience facets and a concise human-readable reason.
- Added a 21-day expiry policy for semantic scores; fresh scores are blended and old scores cannot switch the entire ranking mode.
- Added reviewed public gaps for Taipei Jazz Festival, Taipei Flea Market and Andr while retaining uncertain examples only as taste evidence.
- Published the mobile-first `有空` browser with search, shareable filters, saved/hidden local state, outbound provenance and ICS export.
- Updated Telegram to select across series and experiential lenses, show reasons instead of raw scores, and link to the full browser.
- Added a daily GitHub Pages refresh with health gates, tests and no paid model API.
- Added shareable daytime/evening filtering without guessing a period for date-only events.
- Added Telegram `/events` and `/event <URL> [note]` entry points backed by the local typed inbox.

## Deviations

- The first public build exposed 462 useful events from seven sources rather than the nine-source local snapshot because source availability differs on the GitHub runner. The health gate passed and the public status reports the actual source mix.
- Exact dates were not invented for the abbreviated `晴空祭`, Taichung museum and U-TIX examples. They remain low-confidence taste context until a primary public listing is available.
- Browser feedback remains device-local; cross-device sync was deliberately not introduced.

## Verification

- `PYTHONPATH=code .venv/bin/python -m unittest tests.test_taste tests.test_site -v`: 9/9 passed.
- `npm run build && npm run check`: local snapshot 394 events from nine sources through 2026-12-28.
- `npm run smoke`: mobile and desktop search, daytime/evening URL state, save, hide/restore, ICS and overflow checks passed.
- `daily-event-recommend --dry-run`: current taste-v3 reasons, four diversified picks and the public browser link verified without paid scoring.
- GitHub Actions run `33305162325`: collection, unit tests, build health, browser smoke and Pages deployment all succeeded.
- External read-back on 2026-08-30: homepage HTTP 200; deployed snapshot 462 events from seven sources through 2026-12-28.
- External Playwright: 390x844 and 1440x1000 both returned 18 initial cards with zero horizontal overflow; `台北蚤之市` search returned one result.
- Follow-up GitHub Actions run `33310192548`: period-filter browser smoke and Pages deployment succeeded; live read-back contains the `period-filters` control and `matchesPeriod` logic.
- Follow-up live snapshot: 464 events from seven sources, generated 2026-08-30 20:02 Asia/Taipei, through 2026-12-28.

## Artifacts

- Public site: `https://yhhuan.github.io/event-radar/`
- Event Radar implementation commit: `e7b83a0f73de796b796fd9ed217bff8a9b447e86`
- Telegram integration commit: `578d88a` in private `YHHuan/machine-setup`
- GitHub Actions run: `https://github.com/YHHuan/event-radar/actions/runs/33305162325`
- Period-filter implementation commit: `19df74efba4310a75cf54b589bff76b2acb93fb0`
- Follow-up GitHub Actions run: `https://github.com/YHHuan/event-radar/actions/runs/33310192548`
- Authoritative work record: this directory

## Remaining limits

- Coverage is discovery-oriented, not exhaustive. Event schedule, price and availability remain authoritative on the linked source.
- Some public poster hosts reject hotlinking; the interface intentionally falls back to a stable typographic visual.
- Real-world taste quality remains Yen-Hsun's human acceptance gate. The next revision should use explicit `高權重 / 值追 / 不合 / 錯誤` feedback rather than inferring from clicks.
