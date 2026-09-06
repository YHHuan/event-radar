# Plan: Durable and portable event favorites

Upstream intent: `.ake/work/durable-portable-favorites/intent.md`
Upstream spec: `.ake/work/durable-portable-favorites/spec.md`
Status: completed

## Change surface

- `web/app.js`: versioned favorite records, migration/reconciliation, atomic writes,
  count/status UI and explicit share/import flow.
- `web/index.html` and `web/styles.css`: compact saved count, share control and live status.
- `tests/site-smoke.mjs`: browser-boundary and failure-path coverage.

## Work order

1. Add the storage schema and migration while continuing to read v1 IDs.
2. Reconcile saved records against current public identity and retain snapshots when an
   event is temporarily absent.
3. Add explicit favorites sharing/import and write-status feedback.
4. Exercise same-browser reload, old-ID migration, cross-context import and write failure.

## Highest-risk assumption

A bounded event snapshot is small enough for `localStorage`; saved records are therefore
limited and store only public fields needed to render a card.

## Proof

- `npm run build && npm run check && npm run smoke`
- `PYTHONPATH=code .venv/bin/python -m unittest discover -s tests -p 'test_*.py' -v`
