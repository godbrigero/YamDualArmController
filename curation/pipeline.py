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

# winnow's paths.CAMS; every episode needs all of them plus its npz
CAMS = ("top", "wrist_1", "wrist_2")
REQUIRED = ("data.npz", *(f"{cam}.mp4" for cam in CAMS))

# Stages whose artifact is rewritten wholesale from the current corpus, so a
# deleted episode disappears from it after one run. `transcode` is not one of
# them: it only ever adds files, so its leftovers would look stale forever and
# re-run the stage on every invocation. They are also inert — ingest reads
# transcodes by episode name and never enumerates the directory.
STALE_MATTERS = ("vision", "ingest", "features", "detect", "residual")

# a stage that re-runs invalidates whatever consumed its output: ingest is what
# links the transcodes into the .rrd, and detect is what folds residual.json
# into the panel. Both consumers run later in the stage order, so forcing them
# when their producer runs is enough — and it keeps an unchanged corpus from
# redoing either of them on every invocation.
DEPENDENTS = {"transcode": "ingest", "residual": "detect"}


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
        # A directory is not enough: transcode.py self-skips per file, so an
        # interrupted run leaves an episode with only some of its cameras and
        # ingest would silently attach just those. Match transcode.py's own
        # resume rule — non-zero size — so a 0-byte output is not counted as
        # finished. Note this inherits winnow's limitation: an mp4 truncated
        # mid-encode is non-zero and neither this nor transcode.py can tell it
        # from a complete one. `--refresh` is the way out of that.
        return {os.path.basename(path)
                for path in glob.glob(os.path.join(target, "episode_*"))
                if all(os.path.getsize(clip) if os.path.exists(clip) else 0
                       for clip in (os.path.join(path, f"{cam}.mp4") for cam in CAMS))}
    try:
        with open(target) as handle:
            return set(json.load(handle))
    except (OSError, ValueError):
        return set()


def prune_orphans(src: str) -> None:
    """Set aside `.rrd`s whose episode folder is gone, so the corpus cannot lie.

    `open_corpus` globs every `.rrd` it finds, so a recording deleted after
    ingest would otherwise still be served, judged, and reported as kept.

    They are moved rather than deleted. An `.rrd` is expensive to rebuild, and
    "the episode folder is gone" is also what archiving raw footage to cold
    storage looks like — that must not silently destroy the derived recordings.
    """
    live = episode_names(src)
    orphans = [path for path in glob.glob(os.path.join(artifact(src, "rrd"), "*.rrd"))
               if os.path.basename(path)[: -len(".rrd")] not in live]
    if not orphans:
        return

    # a subdirectory is enough to hide them: open_corpus globs rrd/*.rrd
    aside = artifact(src, os.path.join("rrd", "orphaned"))
    os.makedirs(aside, exist_ok=True)
    for path in orphans:
        name = os.path.basename(path)
        # an episode recorded, ingested, deleted and recorded again under the
        # same number would otherwise overwrite the copy already set aside
        destination, suffix = os.path.join(aside, name), 1
        while os.path.exists(destination):
            destination = os.path.join(aside, f"{name[: -len('.rrd')]}.{suffix}.rrd")
            suffix += 1
        shutil.move(path, destination)
    print(f"[curate] set aside {len(orphans)} recording(s) with no episode folder "
          f"-> {os.path.relpath(aside, os.path.abspath(src))}", flush=True)


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


def owed_marker(src: str, consumer: str) -> str:
    return artifact(src, f".{consumer}-owed")


def run_pipeline(src: str, stages=DEFAULT_STAGES, refresh=False) -> list[str]:
    """Run the named winnow stages over `src`. Returns any preflight warnings.

    A stage is skipped only when its artifact accounts for exactly the current
    corpus and nothing it depends on has been rebuilt since. `refresh` re-runs
    everything.
    """
    require_submodule()
    warnings = preflight(src)
    os.makedirs(data_dir(src), exist_ok=True)
    prune_orphans(src)
    episodes = episode_names(src)

    for stage in stages:
        accounted = covered(src, stage)
        missing = episodes - accounted
        stale = (accounted - episodes) if stage in STALE_MATTERS else set()
        # a debt recorded on disk, so that a consumer killed or failed after its
        # producer succeeded is still re-run on the next invocation. Held only in
        # memory, both stages would look "already done" forever after — and for
        # residual -> detect that means a panel with the stray-debris detector
        # silently missing, which keeps bad episodes rather than just looking wrong.
        owed = os.path.exists(owed_marker(src, stage))
        if not refresh and not owed and not missing and not stale:
            print(f"[curate] {stage}: already done ({len(episodes)} episodes)", flush=True)
            continue
        if refresh:
            reason = "forced"
        elif owed:
            reason = "its input was rebuilt"
        elif missing:
            reason = f"{len(missing)} of {len(episodes)} episodes outstanding"
        else:
            # an episode was deleted after this artifact was written; regenerate
            # rather than let a ghost be judged and reported
            reason = f"{len(stale)} episodes no longer exist"
        # transcode is the one stage that self-skips per output file, so a
        # refresh has to clear it to have any effect — and a truncated mp4 from
        # an interrupted run would otherwise never be replaced. Every other
        # stage rewrites its artifact in place, where deleting first would only
        # mean a failed re-run leaves nothing behind.
        target = artifact(src, ARTIFACTS[stage])
        if stage == "transcode" and refresh and os.path.isdir(target):
            shutil.rmtree(target)
        print(f"[curate] {stage}: running ({reason})", flush=True)
        # detect.py ends by scoring itself against the hand labels of winnow's own
        # reference corpus, which say nothing about this one. The firings we care
        # about come back through detections.json.
        quiet = stage in ("detect", "residual")
        # The debt is owed the moment this stage starts touching its output, not
        # when it exits 0 — a stage can leave complete-looking output and still
        # fail, and then nothing would ever tell the consumer to re-run.
        if stage in DEPENDENTS:
            open(owed_marker(src, DEPENDENTS[stage]), "w").close()
        try:
            _run(os.path.join("winnow", f"{stage}.py"), src, quiet=quiet)
        except WinnowError:
            # residual.py writes residual.json and *then* crashes rendering debug
            # overlays for hardcoded episode ids from winnow's own corpus. That is
            # survivable — but only if the scores it wrote actually cover this
            # corpus, rather than being a stale file from an earlier run.
            if stage == "residual" and not (episodes - covered(src, "residual")):
                warnings.append(
                    "winnow's residual.py failed after writing residual.json (it renders "
                    "debug overlays for episode ids from its own corpus). The stray-debris "
                    "scores were still produced and are being used."
                )
                _discharge(src, stage)
                continue
            raise
        _discharge(src, stage)
    return warnings


def _discharge(src: str, stage: str) -> None:
    """Clear this stage's own debt, now that it has succeeded."""
    marker = owed_marker(src, stage)
    if os.path.exists(marker):
        os.remove(marker)


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
        stderr = (getattr(error.__cause__, "stderr", "") or "").strip()
        # "Schema error" is an unknown column, "SQL error" a malformed clause;
        # anything else (uv missing, a dead catalog) has its own better message
        if not any(kind in stderr for kind in ("Schema error", "SQL error")):
            raise
        # DataFusion's schema error is much easier to act on next to the column
        # list, and its traceback above that line is all internals
        raise WinnowError(
            f"the query failed. Available columns: {', '.join(METRIC_COLUMNS)}.\n"
            f"  --where {where}\n  " + "\n  ".join(stderr.splitlines()[-2:])
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
