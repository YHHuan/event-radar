# Spec: Durable and portable event favorites

Upstream intent: `.ake/work/durable-portable-favorites/intent.md`
Status: accepted for implementation

## Storage contract

- Version 2 stores at most 200 public event snapshots in browser `localStorage`.
- Version 1 ID arrays migrate after the current public feed loads and remain as a
  rollback bridge.
- Reconciliation prefers exact ID, then a tracking-parameter-free public URL, then
  normalized title/city within a bounded date distance.
- A write must succeed before the visible saved state changes.

## Portability and privacy

- Favorites remain browser-local by default.
- Only an explicit `Share favorites` action creates a URL containing saved public event
  IDs; hidden events, browsing history and other personal data are excluded.
- Import is bounded to 200 syntactically valid IDs and resolves only IDs present in the
  public feed.
- No account, server-side personal state, analytics or credential is introduced.

## Publication gate

- Named approver: Yen-Hsun Huang.
- Gate decision: the reported production persistence fault authorizes a scoped repair to
  the already-approved public Event Radar.

## Rollback

- Revert the favorite UI/application commit. Version 1 remains written by version 2, so
  rollback restores the prior ID-only behavior without a data migration.
- Remove the `favorites` query parameter from any shared URL to prevent import.
