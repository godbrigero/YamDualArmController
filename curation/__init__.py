"""Episode triage: decide which recordings are good enough to train on.

The measurements come from [winnow](https://github.com/AdamEXu/winnow), vendored
as a submodule under `third_party/winnow`. Winnow ingests each `episode_XXXX/`
into a Rerun `.rrd`, serves the corpus as a catalog, and reduces it to one row
per episode in SQL. This package wraps that pipeline, turns its output into a
keep/reject decision, and writes the decision next to the episodes as
`curation.json` so conversion and upload can honour it.

The episode layout winnow expects is exactly what `episode_writer.py` produces —
`episode_XXXX/{top,wrist_1,wrist_2}.mp4` plus `data.npz` and `meta.json` — so no
translation step is needed.
"""

from curation.manifest import (
    DEFAULT_DETECTORS,
    DEFAULT_WHERE,
    RIG_AGNOSTIC_DETECTORS,
    TASK_SPECIFIC_DETECTORS,
    Manifest,
    decide,
    load_manifest,
    manifest_path,
    write_manifest,
)
from curation.pipeline import WinnowError, episode_dirs, run_pipeline, query_metrics

__all__ = [
    "DEFAULT_DETECTORS",
    "DEFAULT_WHERE",
    "RIG_AGNOSTIC_DETECTORS",
    "TASK_SPECIFIC_DETECTORS",
    "Manifest",
    "WinnowError",
    "decide",
    "episode_dirs",
    "load_manifest",
    "manifest_path",
    "query_metrics",
    "run_pipeline",
    "write_manifest",
]
