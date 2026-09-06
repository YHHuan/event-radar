# Intent: Durable and portable event favorites

Owner: Yen-Hsun Huang
Status: accepted
Source of truth: this file

## Problem

The public Event Radar can appear to lose hearted events. Favorites currently store only
internal event IDs in browser-local storage. A changed event ID makes the saved item
unresolvable, and Telegram's in-app browser cannot see Chrome's storage. A failed storage
write also looks successful until the next page load.

## Observable outcome

- Existing version-1 favorites migrate without user action.
- A favorite remains usable when the current feed changes its internal ID but retains the
  same public event identity.
- Storage failure is visible and does not leave a false saved state.
- The saved count is visible, and a user-triggered share link can import the current
  favorites into another browser without an account or server-side personal data.

## Boundaries

- Keep favorites private to the browser unless the user explicitly shares a favorites link.
- Do not add accounts, credentials, analytics or a write API.
- Do not include hidden events in shared links.
- Preserve unrelated collector changes in the working tree.

## Acceptance evidence

- Playwright verifies reload persistence, v1 migration, changed-ID reconciliation,
  portable import and a failed-write state.
- Unit, static data-health and browser smoke checks pass.
