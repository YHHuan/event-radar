# Result: Durable and portable event favorites

Upstream plan: `.ake/work/durable-portable-favorites/plan.md`
Terminal state: deployed and field-verified

## Outcome

- Recovered and read back 10 existing favorites from Chrome Profile 2; all 10 still
  resolve in the live public feed.
- Added a version-2 saved-event record that retains enough public metadata to render a
  favorite even when it is temporarily absent from a later feed.
- Added automatic version-1 migration and current-event reconciliation across changed IDs.
- Added an atomic storage failure path, visible saved count, status feedback, and an
  explicit favorites share/import URL for crossing the Chrome/Telegram browser boundary.
- Kept version-1 IDs as a rollback bridge and introduced no backend or personal-data upload.

## Verification

- Python unit suite: 11/11 passed.
- Static build: 447 events from 9 sources through 2026-12-28.
- Static health check: passed.
- Playwright smoke: passed at 390x844 and 1440x1000, including reload persistence,
  version-1 migration, changed-ID reconciliation, fresh-context import and denied-write
  rollback.
- Visual read-back: saved mobile view showed 10 results, `收藏 10`, share control and no
  horizontal overflow.
- GitHub Actions run `34041440748` completed successfully for commit `fee4dfa`, including
  production source refresh, browser smoke and Pages deployment.
- Production read-back at `https://yhhuan.github.io/event-radar/` loaded the actual copied
  Chrome Profile 2 state and reported `v1=10`, `v2=10`, 10 rendered results and badge 10.

## Remaining limitation

Chrome and Telegram in-app storage remain separate by browser design. Crossing that
boundary requires the explicit share/import action; automatic account sync would require
a consented authenticated backend and is intentionally outside this repair.
