"""The keep/reject decision, and the manifest that records it.

Nothing in this module imports winnow or rerun. It takes the two artifacts the
winnow pipeline produces — per-episode metrics (from the catalog's SQL
reduction) and detector firings (from `detect.py`) — and reduces them to a list
of episodes worth training on, plus a reason for every rejection.

Two independent filters decide it:

    predicate   a SQL `WHERE` clause over the metrics, evaluated by DataFusion
                inside winnow's catalog. Rejects on aggregate capture quality.
    detectors   named defects, each of which explains itself in a sentence with
                a frame or a coordinate in it.

Detectors are opt-in by name because winnow's panel was built for one rig and
one task — sweeping pasta into a basket. `capture_stall` and `truncated`
measure the recorder and transfer to any rig; `task_not_completed` and
`debris_outside_basket` read yellow pixels off the top camera and mean nothing
unless your task also involves yellow debris.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

MANIFEST_NAME = "curation.json"

# Defects of the recording itself: a gap with no data in it, or an episode far
# shorter than any complete demonstration. Both transfer to any rig.
RIG_AGNOSTIC_DETECTORS = ("capture_stall", "truncated")

# Defects of the *task*, read off the top camera's yellow pixels. Only
# meaningful on the sweeping rig winnow was calibrated against.
TASK_SPECIFIC_DETECTORS = ("task_not_completed", "debris_outside_basket")

DEFAULT_DETECTORS = RIG_AGNOSTIC_DETECTORS

# Aggregate capture quality, in the columns catalog.py's SQL emits. A third of
# winnow's reference corpus arrived a full period late, so the bar is on the
# rate of dropped ticks rather than on the nominal fps nobody achieved.
DEFAULT_WHERE = "pct_dropped < 40 AND worst_gap_ms < 500"


@dataclass
class Manifest:
    """What was kept, what was not, and the rule that decided it."""

    kept: list[str]
    rejected: dict[str, list[str]]
    query: str = DEFAULT_WHERE
    detectors: list[str] = field(default_factory=lambda: list(DEFAULT_DETECTORS))
    metrics: dict[str, dict] = field(default_factory=dict)
    source: str = ""
    winnow_commit: str = ""

    @property
    def episodes(self) -> list[str]:
        return list(self.kept)

    def summary(self) -> str:
        total = len(self.kept) + len(self.rejected)
        return f"kept {len(self.kept)} of {total} episodes"

    def reasons(self) -> str:
        return "\n".join(
            f"  {name}: {'; '.join(why)}" for name, why in sorted(self.rejected.items())
        )


def manifest_path(src: str) -> str:
    return os.path.join(src, MANIFEST_NAME)


def load_manifest(src_or_path: str) -> Manifest | None:
    """Read a manifest from an episode directory or a direct path. None if absent."""
    path = src_or_path
    if os.path.isdir(src_or_path):
        path = manifest_path(src_or_path)
    if not os.path.exists(path):
        return None
    with open(path) as handle:
        raw = json.load(handle)
    known = {f.name for f in Manifest.__dataclass_fields__.values()}
    return Manifest(**{k: v for k, v in raw.items() if k in known})


def write_manifest(src: str, manifest: Manifest) -> str:
    path = manifest_path(src)
    with open(path, "w") as handle:
        json.dump(asdict(manifest), handle, indent=2)
    return path


def decide(metrics, detections, where=DEFAULT_WHERE, detectors=DEFAULT_DETECTORS,
           kept_by_query=None, source="", winnow_commit=""):
    """Combine the SQL survivors with the detector panel into one decision.

    `metrics` is a list of per-episode rows from winnow's catalog, each with an
    `episode` key. `detections` maps an episode name to the list of detectors
    that fired on it. `kept_by_query` is the episode list DataFusion returned
    for `where`; when it is None the predicate is treated as having passed
    everything, which is what happens if the query could not be run.
    """
    detectors = tuple(detectors)
    by_episode = {row["episode"]: row for row in metrics}
    names = sorted(set(by_episode) | set(detections or {}))
    survived_query = set(names if kept_by_query is None else kept_by_query)

    kept, rejected = [], {}
    for name in names:
        why = []
        if name not in survived_query:
            why.append(f"failed `{where}` ({_numbers(by_episode.get(name))})")
        for hit in (detections or {}).get(name, []):
            if hit.get("detector") in detectors:
                why.append(f"{hit['detector']}: {hit.get('why', '')}".strip())
        if why:
            rejected[name] = why
        else:
            kept.append(name)

    return Manifest(
        kept=kept,
        rejected=rejected,
        query=where,
        detectors=list(detectors),
        metrics=by_episode,
        source=source,
        winnow_commit=winnow_commit,
    )


def filter_episodes(episode_paths, manifest: Manifest):
    """Keep only the paths whose basename the manifest kept. Returns (kept, skipped)."""
    allowed = set(manifest.kept)
    kept, skipped = [], []
    for path in episode_paths:
        (kept if os.path.basename(path.rstrip("/")) in allowed else skipped).append(path)
    return kept, skipped


def _numbers(row):
    """The metrics that predicates are usually written against, for the reason string."""
    if not row:
        return "no metrics"
    interesting = ("pct_dropped", "worst_gap_ms", "duration_s", "true_hz", "debris_end")
    parts = [f"{k}={row[k]:g}" for k in interesting if isinstance(row.get(k), (int, float))]
    return ", ".join(parts) or "no metrics"
