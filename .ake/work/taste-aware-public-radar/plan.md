# Plan: Taste-aware public event radar

Upstream intent: `.ake/work/taste-aware-public-radar/intent.md`
Upstream spec: `.ake/work/taste-aware-public-radar/spec.md`
Status: in progress

## Change surface

- Add an explicit taste-example and facet configuration.
- Replace unbounded keyword accumulation with capped, explainable facet scoring.
- Add a deterministic static export and a mobile-first browser interface.
- Add unit, data-health and Playwright browser tests.
- Add a scheduled GitHub Pages workflow.
- Update the machine-level Telegram recommendation ranking and message.

## Order of work

1. Record the taste examples and implement facet classification, score explanation and stale-model handling.
2. Export a bounded future event snapshot with normalized images, performances and public provenance.
3. Build the static search, filter, save, hide and calendar interactions.
4. Update Telegram to use blended current ranking and link to the public view.
5. Run unit, data, browser and dry-run tests; publish only after they pass.

## Highest-risk assumption

The existing collectors provide enough fresh public metadata to make a static browse page useful. The build must display its actual coverage/freshness and fail the scheduled publish when the snapshot is implausibly small or stale.

## Alternatives not chosen

- A public Streamlit server adds a long-running host and exposes a larger stateful surface for a read-mostly use case.
- Paid embeddings or LLM scoring would add cost and a nondeterministic dependency before enough preference feedback exists.
- A generic category-only recommender fails to represent the cross-category experiential pattern in the supplied examples.

## Proof

- `python -m unittest discover -s tests -p 'test_*.py'`
- Static export health command reports future counts, source coverage and maximum update age.
- Playwright smoke test at phone and desktop viewports verifies nonblank content, no horizontal overflow, search/filter state, save/hide persistence and valid outbound links.
- `daily-event-recommend --dry-run` includes current reasons and the GitHub Pages URL.
- `curl` and GitHub deployment metadata confirm the public page after deployment.

## Human gates

- Publication approval: Yen-Hsun Huang, granted in the originating request.
- Taste-quality acceptance: Yen-Hsun after real-world use; browser feedback remains reversible and local.
