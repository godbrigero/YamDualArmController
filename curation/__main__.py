"""Triage a recorded dataset, and write down which episodes survived.

    uv run -m curation --src episodes/<dataset>

Runs winnow over the episodes, reduces the corpus to one row each in SQL over
the Rerun catalog, applies a predicate and the detector panel, and writes
`episodes/<dataset>/curation.json`. Conversion and upload read that file, so the
episodes a defect fired on never reach the Hub.

    uv run -m curation --src episodes/<dataset> \
        --where "pct_dropped < 25 AND worst_gap_ms < 300" \
        --detectors capture_stall,truncated

    uv run -m curation --src episodes/<dataset> --list        # decision only
    uv run -m curation --src episodes/<dataset> --view        # open the viewer
"""

from __future__ import annotations

import argparse
import glob
import os
import subprocess
import sys

from curation.manifest import (
    DEFAULT_DETECTORS,
    DEFAULT_WHERE,
    RIG_AGNOSTIC_DETECTORS,
    TASK_SPECIFIC_DETECTORS,
    decide,
    load_manifest,
    write_manifest,
)
from curation.pipeline import (
    DEFAULT_STAGES,
    WINNOW_DIR,
    WinnowError,
    artifact,
    load_detections,
    query_metrics,
    require_submodule,
    run_pipeline,
    winnow_commit,
)

ALL_DETECTORS = RIG_AGNOSTIC_DETECTORS + TASK_SPECIFIC_DETECTORS


def parse_detectors(value: str) -> tuple[str, ...]:
    if value == "all":
        return ALL_DETECTORS
    if value in ("none", ""):
        return ()
    names = tuple(name.strip() for name in value.split(",") if name.strip())
    unknown = [name for name in names if name not in ALL_DETECTORS]
    if unknown:
        raise SystemExit(f"unknown detector(s): {', '.join(unknown)}. "
                         f"known: {', '.join(ALL_DETECTORS)}, or 'all' / 'none'")
    return names


def view(src: str, flagged_only: bool) -> int:
    """Open the corpus in the Rerun viewer, so a rejection can be overturned by eye."""
    require_submodule()
    manifest = load_manifest(src)
    recordings = []
    if flagged_only:
        if manifest is None:
            print(f"no curation.json in {src}; showing the whole corpus")
        else:
            recordings = [artifact(src, os.path.join("rrd", f"{name}.rrd"))
                          for name in sorted(manifest.rejected)]
            if not recordings:
                print("nothing was rejected; showing the whole corpus instead")
    recordings = recordings or sorted(glob.glob(artifact(src, os.path.join("rrd", "*.rrd"))))
    if not recordings:
        raise SystemExit(f"nothing ingested for {src}; run `uv run -m curation --src {src}` first")
    command = ["uv", "run", "--quiet", "rerun", *recordings]
    return subprocess.run(command, cwd=WINNOW_DIR).returncode


def report(manifest, warnings) -> None:
    for warning in warnings:
        print(f"[curate] warning: {warning}")
    print(f"\n{manifest.summary()}")
    if manifest.rejected:
        print("rejected:")
        print(manifest.reasons())


def main() -> int:
    parser = argparse.ArgumentParser(prog="curation", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--src", default="episodes/default",
                        help="directory of episode_XXXX folders (default: episodes/default)")
    parser.add_argument("--where", default=DEFAULT_WHERE,
                        help=f"SQL predicate over the metrics (default: {DEFAULT_WHERE!r})")
    parser.add_argument("--detectors", default=",".join(DEFAULT_DETECTORS),
                        help="comma-separated detector names, or 'all' / 'none'. "
                             f"rig-agnostic: {', '.join(RIG_AGNOSTIC_DETECTORS)}; "
                             f"sweeping-rig only: {', '.join(TASK_SPECIFIC_DETECTORS)}")
    parser.add_argument("--transcode", action="store_true",
                        help="also re-encode to H.264 so the footage plays in the viewer")
    parser.add_argument("--refresh", action="store_true",
                        help="re-run stages whose artifacts already exist")
    parser.add_argument("--list", action="store_true",
                        help="print the existing decision without re-running anything")
    parser.add_argument("--view", action="store_true", help="open the corpus in the Rerun viewer")
    parser.add_argument("--view-rejected", action="store_true",
                        help="open only the episodes that were rejected")
    args = parser.parse_args()

    if args.view or args.view_rejected:
        return view(args.src, args.view_rejected)

    if args.list:
        manifest = load_manifest(args.src)
        if manifest is None:
            print(f"no curation.json in {args.src}; run `uv run -m curation --src {args.src}`")
            return 1
        report(manifest, [])
        return 0

    detectors = parse_detectors(args.detectors)
    stages, force = list(DEFAULT_STAGES), set()
    if args.transcode:
        stages.insert(1, "transcode")
        # ingest.log_video is what links the transcodes into the .rrd, so
        # transcoding an already-ingested corpus achieves nothing on its own
        force.add("ingest")
    if "debris_outside_basket" in detectors:
        # residual.json has to exist before detect.py folds the stray-debris
        # detector into the panel, so detect runs after it and runs again
        stages.insert(stages.index("detect"), "residual")
        force.add("detect")

    warnings = run_pipeline(args.src, stages=stages, refresh=args.refresh, force=force)
    metrics, kept_by_query = query_metrics(args.src, args.where)
    manifest = decide(
        metrics,
        load_detections(args.src),
        where=args.where,
        detectors=detectors,
        kept_by_query=kept_by_query,
        source=os.path.abspath(args.src),
        winnow_commit=winnow_commit(),
    )

    path = write_manifest(args.src, manifest)
    report(manifest, warnings)
    print(f"\nwrote {path}")
    print("conversion and upload read this file; re-run with a different --where to change it.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except WinnowError as error:
        raise SystemExit(f"curate: {error}")
