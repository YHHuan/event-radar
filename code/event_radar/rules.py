"""First-stage deterministic taste rules; semantic scoring is optional evidence."""
from __future__ import annotations

from .taste import analyze_event


def score_event(ev: dict) -> dict:
    """Populate bounded score, decision and explainable tags in-place."""
    analysis = analyze_event(ev)
    ev["base_score"] = analysis["score"]
    ev["rule_decision"] = analysis["decision"]
    ev["noise_flags"] = analysis["negative_matches"]
    derived_tags = [item["label"] for item in analysis["lenses"]]
    derived_tags += [item["label"] for item in analysis["facets"]]
    ev["tags"] = sorted(set((ev.get("tags") or []) + derived_tags))
    return ev
