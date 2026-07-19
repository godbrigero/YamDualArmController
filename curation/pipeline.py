"""Driving winnow's pipeline over a recorded episode directory.

Winnow is a submodule with its own pinned environment (`rerun-sdk==0.34.1`,
`datafusion~=53.0`) that would conflict with this project's, so every stage runs
as a subprocess under `uv run` inside `third_party/winnow`. It is told where to
find the episodes and where to put its artifacts through the two environment
variables `paths.py` reads:

    WINNOW_SRC    episodes/<dataset>            the episode_XXXX folders
    WINNOW_DATA   episodes/<dataset>/.winnow    everything derived from them

Stages, in order, and the artifact each one leaves behind:

    vision      video_features.json   debris, motion and luma, per frame
    transcode   video_h264/           MPEG-4 Part 2 -> H.264, for the viewer
    ingest      rrd/*.rrd             one queryable recording per episode
    features    features.json         one physical feature vector per episode
    detect      detections.json       which defects fired, and why
    residual    residual.json         debris left outside the basket

`transcode` and `residual` are off by default: the first only matters if you
want to scrub the footage in the Rerun viewer, and the second is calibrated to
winnow's sweeping rig.
"""

from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WINNOW_DIR = os.path.join(ROOT, "third_party", "winnow")
QUERY_SCRIPT = os.path.join(ROOT, "curation", "_query.py")

# stage -> the artifact that means it has already run
ARTIFACTS = {
    "vision": "video_features.json",
    "transcode": "video_h264",
    "ingest": "rrd",
    "features": "features.json",
    "detect": "detections.json",
    "residual": "residual.json",
}
DEFAULT_STAGES = ("vision", "ingest", "features", "detect")

# every episode needs these before winnow can read it; the recorder writes them
REQUIRED = ("data.npz", "top.mp4", "wrist_1.mp4", "wrist_2.mp4")


class WinnowError(RuntimeError):
    """A winnow stage failed, or the submodule is not there to run."""


def data_dir(src: str) -> str:
    # absolute, because every winnow stage runs with cwd=WINNOW_DIR: a path
    # relative to the caller would resolve inside the submodule instead
    return os.path.abspath(os.path.join(src, ".winnow"))


def artifact(src: str, name: str) -> str:
    return os.path.join(data_dir(src), name)


def episode_dirs(src: str) -> list[str]:
    return sorted(glob.glob(os.path.join(src, "episode_*")))


def episode_names(src: str) -> set:
    return {os.path.basename(path) for path in episode_dirs(src)}


def require_submodule() -> None:
    if not os.path.exists(os.path.join(WINNOW_DIR, "winnow", "catalog.py")):
        raise WinnowError(
            f"winnow is not checked out at {WINNOW_DIR}.\n"
            "  git submodule update --init third_party/winnow"
        )


def winnow_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=WINNOW_DIR,
                             capture_output=True, text=True, check=True)
        return out.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def preflight(src: str) -> list[str]:
    """Check the corpus is shaped the way winnow's stages assume. Returns warnings."""
    episodes = episode_dirs(src)
    if not episodes:
        raise WinnowError(f"no episode_* folders in {src}")

    incomplete = {
        os.path.basename(episode): [f for f in REQUIRED
                                    if not os.path.exists(os.path.join(episode, f))]
        for episode in episodes
    }
    incomplete = {k: v for k, v in incomplete.items() if v}
    if incomplete:
        listed = "\n".join(f"  {k}: missing {', '.join(v)}" for k, v in sorted(incomplete.items()))
        raise WinnowError(
            "every episode needs all three cameras and its data.npz before winnow "
            f"can read it:\n{listed}\n"
            "Move or delete the incomplete recordings and re-run."
        )

    warnings = []
    declared = set()
    for episode in episodes:
        meta = os.path.join(episode, "meta.json")
        if os.path.exists(meta):
            with open(meta) as handle:
                declared.add(json.load(handle).get("fps"))
    off_nominal = {fps for fps in declared if fps not in (None, 15)}
    if off_nominal:
        warnings.append(
            f"episodes declare fps {sorted(off_nominal)}, but winnow's dropped-tick "
            "threshold is hardwired to 15 (paths.NOMINAL_FPS). pct_dropped will be "
            "measured against the wrong period — adjust the predicate accordingly."
        )
    return warnings


def _env(src: str) -> dict:
    env = dict(os.environ)
    env["WINNOW_SRC"] = os.path.abspath(src)
    env["WINNOW_DATA"] = os.path.abspath(data_dir(src))
    env["PYTHONPATH"] = os.path.join(WINNOW_DIR, "winnow")
    return env


def covered(src: str, stage: str) -> set:
    """Which episodes a stage's artifact actually accounts for.

    The artifact existing is not the same as it being complete. Two ordinary
    things make them diverge: an interrupted run leaves a partial `rrd/`, and
    recording ten more episodes into a dataset that was curated last week
    leaves every artifact a subset of the corpus. Skipping on existence alone
    would quietly drop those episodes from the manifest — they would appear in
    neither `kept` nor `rejected`, and conversion would never see them.
    """
    target = artifact(src, ARTIFACTS[stage])
    if not os.path.exists(target):
        return set()
    if stage == "ingest":
        return {os.path.basename(path)[: -len(".rrd")]
                for path in glob.glob(os.path.join(target, "*.rrd"))}
    if stage == "transcode":
        return {os.path.basename(path) for path in glob.glob(os.path.join(target, "episode_*"))}
    try:
        with open(target) as handle:
            return set(json.load(handle))
    except (OSError, ValueError):
        return set()


def prune_orphans(src: str) -> None:
    """Drop `.rrd`s whose episode folder is gone, so the corpus cannot lie.

    `open_corpus` globs every `.rrd` it finds, so a recording deleted after
    ingest would otherwise still be served, judged, and listed as kept.
    """
    live = episode_names(src)
    for path in glob.glob(os.path.join(artifact(src, "rrd"), "*.rrd")):
        if os.path.basename(path)[: -len(".rrd")] not in live:
            print(f"[curate] dropping {os.path.basename(path)}: no such episode any more",
                  flush=True)
            os.remove(path)


def _run(script: str, src: str, extra=(), quiet=False) -> None:
    command = ["uv", "run", "--quiet", "python", script, *extra]
    try:
        subprocess.run(command, cwd=WINNOW_DIR, env=_env(src), check=True,
                       capture_output=quiet, text=quiet)
    except FileNotFoundError as error:
        raise WinnowError("uv is not on PATH; winnow's environment is managed by uv") from error
    except subprocess.CalledProcessError as error:
        detail = f"\n{error.stdout}{error.stderr}" if quiet else ""
        raise WinnowError(f"winnow stage failed: {' '.join(command)}{detail}") from error


def run_pipeline(src: str, stages=DEFAULT_STAGES, refresh=False, force=()) -> list[str]:
    """Run the named winnow stages over `src`. Returns any preflight warnings.

    A stage is skipped only when its artifact already accounts for every episode
    in the corpus. `refresh` re-runs everything; `force` re-runs named stages,
    which is how `detect` runs again once `residual` has produced the input it
    folds into the panel.
    """
    require_submodule()
    warnings = preflight(src)
    os.makedirs(data_dir(src), exist_ok=True)
    prune_orphans(src)
    episodes = episode_names(src)

    for stage in stages:
        accounted = covered(src, stage)
        missing, stale = episodes - accounted, accounted - episodes
        if not refresh and stage not in force and not missing and not stale:
            print(f"[curate] {stage}: already done ({len(episodes)} episodes)", flush=True)
            continue
        if refresh or stage in force:
            reason = "forced"
        elif missing:
            reason = f"{len(missing)} of {len(episodes)} episodes outstanding"
        else:
            # an episode was deleted after this artifact was written; regenerate
            # rather than let a ghost be judged and reported
            reason = f"{len(stale)} episodes no longer exist"
        # a directory artifact can hold a half-written file from an interrupted
        # run, and the stages self-skip on existence, so clear it first
        target = artifact(src, ARTIFACTS[stage])
        if refresh and os.path.isdir(target):
            shutil.rmtree(target)
        print(f"[curate] {stage}: running ({reason})", flush=True)
        # detect.py ends by scoring itself against the hand labels of winnow's own
        # reference corpus, which say nothing about this one. The firings we care
        # about come back through detections.json.
        quiet = stage in ("detect", "residual")
        try:
            _run(os.path.join("winnow", f"{stage}.py"), src, quiet=quiet)
        except WinnowError:
            # residual.py writes residual.json and *then* crashes rendering debug
            # overlays for hardcoded episode ids from winnow's own corpus. The
            # artifact we need survives, so a crash after it is written is not fatal.
            if stage == "residual" and os.path.exists(artifact(src, ARTIFACTS["residual"])):
                warnings.append(
                    "winnow's residual.py failed after writing residual.json (it renders "
                    "debug overlays for episode ids from its own corpus). The stray-debris "
                    "scores were still produced and are being used."
                )
                continue
            raise
    return warnings


# what catalog.py's SQL reduction actually emits, for when a predicate names
# something else and DataFusion's schema error needs translating
METRIC_COLUMNS = ("episode", "n_frames", "duration_s", "true_hz", "pct_dropped",
                  "worst_gap_ms", "debris_end", "peak_err_left_j4", "mean_grip_err")


def query_metrics(src: str, where: str):
    """Reduce the ingested corpus in SQL and apply `where`. Returns (metrics, kept)."""
    require_submodule()
    if not glob.glob(os.path.join(artifact(src, "rrd"), "*.rrd")):
        raise WinnowError(f"nothing ingested under {artifact(src, 'rrd')}; run the pipeline first")

    out = artifact(src, "metrics.json")
    try:
        _run(QUERY_SCRIPT, src, ["--where", where, "--out", out], quiet=True)
    except WinnowError as error:
        # by far the likeliest cause is a typo in the predicate, and DataFusion's
        # schema error is much easier to act on next to the available columns
        # the child's traceback is all datafusion internals; its last line is
        # the part that names the offending column
        stderr = (getattr(error.__cause__, "stderr", "") or "").strip().splitlines()
        raise WinnowError(
            f"the query failed. Available columns: {', '.join(METRIC_COLUMNS)}.\n"
            f"  --where {where}\n  " + "\n  ".join(stderr[-2:])
        ) from error
    with open(out) as handle:
        result = json.load(handle)
    print(f"[curate] {len(result['kept'])} of {len(result['metrics'])} episodes satisfy: {where}",
          flush=True)
    return result["metrics"], result["kept"]


def load_detections(src: str) -> dict:
    path = artifact(src, "detections.json")
    if not os.path.exists(path):
        return {}
    with open(path) as handle:
        return json.load(handle)
