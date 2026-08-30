# Intent: Taste-aware public event radar

Owner: Yen-Hsun Huang
Status: accepted
Source of truth: this file

## Problem

The current A-Ke event recommendation is hard to browse, explains taste with opaque scores, and can keep ranking stale July LLM scores ahead of newer events. Broad keywords such as markets, experiences and performances also over-reward generic listings. Telegram exposes only a few direct links and has no useful place to search the wider shortlist.

## Observable outcome

A mobile-first public event page lets Yen-Hsun search, filter, save, hide and open current events. Ranking distinguishes experiential fit such as live presence, curatorial context, urban place, limited editions, scene culture and adult nature observation. Telegram links to that page and uses current, diversified evidence instead of indefinitely trusting stale model scores.

## Affected people and systems

- Yen-Hsun as the primary user
- `event-radar` collection, ranking, static export and GitHub Pages
- `machine-setup/bin/daily-event-recommend` Telegram output
- Existing local SQLite event data and scheduled collectors

## Boundaries and non-goals

- Publish only already-public event metadata and source links.
- Do not publish calendar data, Telegram content, credentials, private feedback or browsing history.
- Browser saves and hides remain local to that browser; no account or cloud sync in this version.
- Do not spend paid LLM API credit.
- Do not promise exhaustive nationwide coverage or ticket availability.
- Preserve source files and pre-existing uncommitted changes.

## Acceptance evidence

- Deterministic ranking tests cover the new taste facets, stale-score handling and diversity.
- The static build passes data health checks and browser smoke tests at mobile and desktop widths.
- GitHub Pages returns the deployed event page and supports search, filters, save/hide and outbound event links.
- Telegram dry-run contains diversified recommendations and the public browse link.

## Open questions

- Exact interpretation of a few abbreviated taste samples remains uncertain; they are retained as low-confidence examples rather than asserted facts.
- Real-world recommendation quality remains a human judgment gate owned by Yen-Hsun after using the page.
