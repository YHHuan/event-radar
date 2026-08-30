# Spec: Taste-aware public event radar

Upstream intent: `.ake/work/taste-aware-public-radar/intent.md`
Status: accepted for implementation

## Product interface

- Public URL: `https://yhhuan.github.io/event-radar/`.
- Default view prioritizes upcoming strong matches without hiding exploration candidates.
- Search covers event title, venue, organizer, city, source, facet and recommendation reason.
- Filters cover time window, location and experiential lens; state is shareable in the URL.
- Save and hide actions persist in browser `localStorage`; hidden items can be restored.
- Each result shows date, location, concise fit reason, public source and an outbound details link.

## Ranking contract

- Score named taste facets once per facet; repeated generic keywords cannot multiply a score without limit.
- Separate relevance from utility, confidence, proximity and freshness.
- Treat old LLM scores as expired after a bounded interval and blend fresh model signals with deterministic evidence instead of switching the whole result set to one mode.
- Diversify the Telegram shortlist across series and experiential lenses.
- Keep cross-city destination events possible, but require stronger fit outside the primary region.

## Data and privacy

- Static export contains public event metadata only.
- Personal browser actions are never included in the GitHub artifact.
- The local SQLite database remains authoritative for collected events; the deployed JSON is a derived snapshot.
- Public event pages remain the authority for schedule, price and availability.

## Publication and schedule gate

- Named approver: Yen-Hsun Huang.
- Gate decision: approved in the 2026-08-30 request to deploy the improved event radar to GitHub and link it from Telegram.
- GitHub Actions may refresh public event data on a schedule without paid API use.

## Rollback and retirement

- Disable the GitHub Pages workflow and Pages publication to stop public updates.
- Revert the Telegram site URL and ranking changes independently of the collector database.
- The static site has no write API, credentials or server-side state to migrate.
- Retire the public page if freshness checks fail repeatedly or the source coverage becomes misleading.

## Security controls

- No secrets in repository or generated site.
- Escape event content before DOM insertion; do not render collected HTML.
- Outbound links allow only `http` or `https` and open with `noopener`/`noreferrer`.
- Use a restrictive Content Security Policy compatible with public poster images.
