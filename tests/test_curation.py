"""The triage decision, without winnow in the loop.

`curation.manifest` is deliberately free of rerun and winnow imports: it takes
the two artifacts the pipeline produces and reduces them to a keep list. These
tests pin that reduction, the round trip through curation.json, and the filter
conversion applies.
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from curation import pipeline
from curation.manifest import (
    DEFAULT_DETECTORS,
    RIG_AGNOSTIC_DETECTORS,
    TASK_SPECIFIC_DETECTORS,
    decide,
    filter_episodes,
    load_manifest,
    manifest_path,
    write_manifest,
)

METRICS = [
    {"episode": "episode_0000", "pct_dropped": 3.0, "worst_gap_ms": 90.0, "duration_s": 44.0},
    {"episode": "episode_0001", "pct_dropped": 71.0, "worst_gap_ms": 140.0, "duration_s": 41.0},
    {"episode": "episode_0002", "pct_dropped": 4.0, "worst_gap_ms": 1211.0, "duration_s": 39.0},
    {"episode": "episode_0003", "pct_dropped": 2.0, "worst_gap_ms": 80.0, "duration_s": 3.0},
]
DETECTIONS = {
    "episode_0000": [],
    "episode_0001": [],
    "episode_0002": [{"detector": "capture_stall", "why": "a 1211 ms gap with no data at all"}],
    "episode_0003": [{"detector": "truncated", "why": "only 3 seconds"},
                     {"detector": "task_not_completed", "why": "40% of the debris remained"}],
}
# what DataFusion returns for the default predicate over METRICS
KEPT_BY_QUERY = ["episode_0000", "episode_0003"]


class DecideTest(unittest.TestCase):
    def decide(self, **kwargs):
        return decide(METRICS, DETECTIONS, kept_by_query=KEPT_BY_QUERY, **kwargs)

    def test_predicate_and_detectors_both_reject(self):
        manifest = self.decide()
        self.assertEqual(manifest.kept, ["episode_0000"])
        self.assertEqual(sorted(manifest.rejected), ["episode_0001", "episode_0002",
                                                     "episode_0003"])

    def test_rejection_carries_the_reason(self):
        manifest = self.decide()
        self.assertIn("pct_dropped=71", manifest.rejected["episode_0001"][0])
        # the stall trips both filters, and both reasons are kept
        self.assertIn("worst_gap_ms=1211", manifest.rejected["episode_0002"][0])
        self.assertIn("1211 ms gap", manifest.rejected["episode_0002"][1])

    def test_task_specific_detectors_are_off_by_default(self):
        # the sweeping-rig detectors read yellow pixels off the top camera and
        # must not reject anything until they are asked for by name
        for detector in TASK_SPECIFIC_DETECTORS:
            self.assertNotIn(detector, DEFAULT_DETECTORS)
        reasons = " ".join(self.decide().rejected["episode_0003"])
        self.assertIn("truncated", reasons)
        self.assertNotIn("task_not_completed", reasons)

    def test_an_episode_with_no_metrics_is_rejected_not_kept(self):
        """The fail-closed path: ingested, detected on, but absent from the SQL.

        This is what happens in production when the metrics frame and the
        detector panel disagree about which episodes exist. An unmeasured
        episode must never reach the Hub on the strength of no evidence.
        """
        metrics = [row for row in METRICS if row["episode"] != "episode_0000"]
        manifest = decide(metrics, DETECTIONS, kept_by_query=["episode_0003"])
        self.assertNotIn("episode_0000", manifest.kept)
        self.assertIn("no metrics", manifest.rejected["episode_0000"][0])

    def test_task_specific_detectors_when_asked_for(self):
        detectors = RIG_AGNOSTIC_DETECTORS + TASK_SPECIFIC_DETECTORS
        reasons = " ".join(self.decide(detectors=detectors).rejected["episode_0003"])
        self.assertIn("task_not_completed", reasons)

    def test_no_detectors_leaves_only_the_predicate(self):
        manifest = self.decide(detectors=())
        self.assertEqual(manifest.kept, ["episode_0000", "episode_0003"])

    def test_a_failed_query_does_not_silently_reject_everything(self):
        manifest = decide(METRICS, DETECTIONS, kept_by_query=None)
        self.assertEqual(manifest.kept, ["episode_0000", "episode_0001"])

    def test_episodes_only_the_detector_knows_about_are_still_judged(self):
        manifest = decide([], {"episode_0009": [{"detector": "capture_stall", "why": "gap"}]},
                          kept_by_query=None)
        self.assertEqual(manifest.kept, [])
        self.assertIn("episode_0009", manifest.rejected)


class ManifestFileTest(unittest.TestCase):
    def test_round_trip(self):
        manifest = decide(METRICS, DETECTIONS, kept_by_query=KEPT_BY_QUERY)
        with tempfile.TemporaryDirectory() as src:
            path = write_manifest(src, manifest)
            self.assertEqual(path, manifest_path(src))
            loaded = load_manifest(src)
        self.assertEqual(loaded.kept, manifest.kept)
        self.assertEqual(loaded.rejected, manifest.rejected)
        self.assertEqual(loaded.query, manifest.query)

    def test_absent_manifest_reads_as_none(self):
        with tempfile.TemporaryDirectory() as src:
            self.assertIsNone(load_manifest(src))

    def test_a_direct_file_path_is_read_too(self):
        """What `convert_to_lerobot.py --curation-manifest <path>` depends on."""
        manifest = decide(METRICS, DETECTIONS, kept_by_query=KEPT_BY_QUERY)
        with tempfile.TemporaryDirectory() as src:
            write_manifest(src, manifest)
            elsewhere = Path(src) / "renamed.json"
            Path(manifest_path(src)).rename(elsewhere)
            self.assertEqual(load_manifest(str(elsewhere)).kept, manifest.kept)
            self.assertIsNone(load_manifest(str(Path(src) / "missing.json")))

    def test_unknown_keys_do_not_break_older_manifests(self):
        with tempfile.TemporaryDirectory() as src:
            Path(manifest_path(src)).write_text(
                json.dumps({"kept": ["episode_0000"], "rejected": {}, "future_field": 1})
            )
            self.assertEqual(load_manifest(src).kept, ["episode_0000"])


class CoverageTest(unittest.TestCase):
    """Which episodes an artifact accounts for — the skip decision rests on this.

    Filesystem only: no winnow, no rerun, nothing spawned.
    """

    def corpus(self, directory, count=3):
        for index in range(count):
            os.makedirs(os.path.join(directory, f"episode_{index:04d}"))
        os.makedirs(pipeline.data_dir(directory), exist_ok=True)
        return {f"episode_{index:04d}" for index in range(count)}

    def test_json_artifacts_are_keyed_by_episode(self):
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            Path(pipeline.artifact(src, "features.json")).write_text(
                json.dumps({"episode_0000": {}, "episode_0001": {}})
            )
            self.assertEqual(pipeline.covered(src, "features"),
                             {"episode_0000", "episode_0001"})

    def test_a_partial_ingest_does_not_count_as_done(self):
        with tempfile.TemporaryDirectory() as src:
            episodes = self.corpus(src)
            rrd = pipeline.artifact(src, "rrd")
            os.makedirs(rrd)
            Path(os.path.join(rrd, "episode_0000.rrd")).write_text("")
            self.assertEqual(episodes - pipeline.covered(src, "ingest"),
                             {"episode_0001", "episode_0002"})

    def test_transcode_needs_every_camera(self):
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            video = pipeline.artifact(src, "video_h264")
            for name, cams in (("episode_0000", pipeline.CAMS), ("episode_0001", ("top",))):
                os.makedirs(os.path.join(video, name))
                for cam in cams:
                    Path(os.path.join(video, name, f"{cam}.mp4")).write_text("encoded")
            # episode_0001 was interrupted after one camera; ingest would
            # otherwise silently attach only that one
            self.assertEqual(pipeline.covered(src, "transcode"), {"episode_0000"})

    def test_a_zero_byte_transcode_does_not_count_as_done(self):
        """av creates the output file before the muxer writes to it, so an
        interrupted re-encode leaves 0-byte mp4s. Counting one as finished would
        hand it to AssetVideo and fail ingest on every subsequent run."""
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            episode = os.path.join(pipeline.artifact(src, "video_h264"), "episode_0000")
            os.makedirs(episode)
            for cam in pipeline.CAMS:
                Path(os.path.join(episode, f"{cam}.mp4")).write_text("encoded")
            Path(os.path.join(episode, f"{pipeline.CAMS[-1]}.mp4")).write_text("")
            self.assertEqual(pipeline.covered(src, "transcode"), set())

    def test_transcode_leftovers_do_not_make_the_stage_rerun_forever(self):
        """transcode only ever adds files, so its stale entries must not count.

        Every other stage rewrites its artifact wholesale, so a deleted episode
        clears after one run. A leftover transcode directory would look stale on
        every invocation and re-run the stage forever.
        """
        self.assertNotIn("transcode", pipeline.STALE_MATTERS)
        for stage in ("vision", "ingest", "features", "detect"):
            self.assertIn(stage, pipeline.STALE_MATTERS)

    def test_missing_artifact_covers_nothing(self):
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            self.assertEqual(pipeline.covered(src, "detect"), set())

    def test_unreadable_artifact_covers_nothing_rather_than_raising(self):
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            Path(pipeline.artifact(src, "detections.json")).write_text("{ truncated")
            self.assertEqual(pipeline.covered(src, "detect"), set())


class OrphanTest(unittest.TestCase):
    def test_recordings_without_an_episode_are_set_aside_not_deleted(self):
        with tempfile.TemporaryDirectory() as src:
            os.makedirs(os.path.join(src, "episode_0000"))
            rrd = pipeline.artifact(src, "rrd")
            os.makedirs(rrd)
            for name in ("episode_0000", "episode_0009"):
                Path(os.path.join(rrd, f"{name}.rrd")).write_text("recording")

            pipeline.prune_orphans(src)

            # the live one is untouched, the orphan is out of the glob but on disk
            self.assertTrue(os.path.exists(os.path.join(rrd, "episode_0000.rrd")))
            self.assertFalse(os.path.exists(os.path.join(rrd, "episode_0009.rrd")))
            aside = os.path.join(rrd, "orphaned", "episode_0009.rrd")
            self.assertEqual(Path(aside).read_text(), "recording")
            self.assertEqual(pipeline.covered(src, "ingest"), {"episode_0000"})

    def test_nothing_to_prune_leaves_no_directory_behind(self):
        with tempfile.TemporaryDirectory() as src:
            os.makedirs(os.path.join(src, "episode_0000"))
            os.makedirs(pipeline.artifact(src, "rrd"))
            pipeline.prune_orphans(src)
            self.assertFalse(os.path.exists(pipeline.artifact(src, "rrd/orphaned")))


class DependencyTest(unittest.TestCase):
    """A consumer that failed after its producer ran must still re-run later.

    Driven with fake stages that write the real artifact shapes, so no winnow,
    no rerun and no subprocess are involved.
    """

    def drive(self, src, stages, failing=(), refresh=False):
        """Run the pipeline with `_run` replaced. Returns the stages it ran."""
        ran = []

        def fake_run(script, source, extra=(), quiet=False):
            stage = os.path.basename(script)[: -len(".py")]
            ran.append(stage)
            if stage in failing:
                raise pipeline.WinnowError(f"{stage} failed")
            names = sorted(pipeline.episode_names(source))
            if stage == "transcode":
                for name in names:
                    os.makedirs(pipeline.artifact(source, f"video_h264/{name}"), exist_ok=True)
                    for cam in pipeline.CAMS:
                        Path(pipeline.artifact(
                            source, f"video_h264/{name}/{cam}.mp4")).write_text("x")
            elif stage == "ingest":
                os.makedirs(pipeline.artifact(source, "rrd"), exist_ok=True)
                for name in names:
                    Path(pipeline.artifact(source, f"rrd/{name}.rrd")).write_text("x")
            else:
                Path(pipeline.artifact(source, pipeline.ARTIFACTS[stage])).write_text(
                    json.dumps({name: [] for name in names})
                )

        original_run, original_require = pipeline._run, pipeline.require_submodule
        pipeline._run, pipeline.require_submodule = fake_run, lambda: None
        try:
            pipeline.run_pipeline(src, stages=stages, refresh=refresh)
        finally:
            pipeline._run, pipeline.require_submodule = original_run, original_require
        return ran

    def corpus(self, directory, count=2):
        for index in range(count):
            episode = os.path.join(directory, f"episode_{index:04d}")
            os.makedirs(episode)
            for name in pipeline.REQUIRED:
                Path(os.path.join(episode, name)).write_text("x")

    def test_repeated_runs_do_no_work(self):
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            stages = ["vision", "ingest", "features", "detect"]
            self.assertEqual(self.drive(src, stages), stages)
            self.assertEqual(self.drive(src, stages), [])

    def test_a_detect_that_failed_after_residual_reruns(self):
        """The case that silently kept bad episodes: detect skipped forever, so
        the panel never folded in the stray-debris detector."""
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            plain = ["vision", "ingest", "features", "detect"]
            self.drive(src, plain)
            with_residual = ["vision", "ingest", "features", "residual", "detect"]
            with self.assertRaises(pipeline.WinnowError):
                self.drive(src, with_residual, failing=("detect",))
            # detect is still owed, so the next run must redo it rather than
            # report "already done" and write a manifest missing the detector
            self.assertEqual(self.drive(src, with_residual), ["detect"])
            self.assertEqual(self.drive(src, with_residual), [])

    def test_an_ingest_that_failed_after_transcode_reruns(self):
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            self.drive(src, ["vision", "ingest", "features", "detect"])
            staged = ["vision", "transcode", "ingest", "features", "detect"]
            with self.assertRaises(pipeline.WinnowError):
                self.drive(src, staged, failing=("ingest",))
            self.assertEqual(self.drive(src, staged), ["ingest"])
            self.assertEqual(self.drive(src, staged), [])

    def test_a_new_episode_reruns_every_stage(self):
        with tempfile.TemporaryDirectory() as src:
            self.corpus(src)
            stages = ["vision", "ingest", "features", "detect"]
            self.drive(src, stages)
            os.makedirs(os.path.join(src, "episode_0002"))
            for name in pipeline.REQUIRED:
                Path(os.path.join(src, "episode_0002", name)).write_text("x")
            self.assertEqual(self.drive(src, stages), stages)


class PathTest(unittest.TestCase):
    def test_artifact_paths_are_absolute(self):
        """Winnow's stages run with cwd set to the submodule, so a relative
        artifact path would resolve inside third_party/winnow instead."""
        self.assertTrue(os.path.isabs(pipeline.data_dir("episodes/demo")))
        self.assertTrue(os.path.isabs(pipeline.artifact("episodes/demo", "metrics.json")))


class FilterTest(unittest.TestCase):
    def test_conversion_sees_only_the_survivors(self):
        manifest = decide(METRICS, DETECTIONS, kept_by_query=KEPT_BY_QUERY)
        paths = [f"episodes/demo/episode_{i:04d}" for i in range(4)]
        kept, skipped = filter_episodes(paths, manifest)
        self.assertEqual(kept, ["episodes/demo/episode_0000"])
        self.assertEqual(len(skipped), 3)

    def test_trailing_slashes_do_not_hide_an_episode(self):
        manifest = decide(METRICS, DETECTIONS, kept_by_query=KEPT_BY_QUERY)
        kept, _ = filter_episodes(["episodes/demo/episode_0000/"], manifest)
        self.assertEqual(len(kept), 1)


if __name__ == "__main__":
    unittest.main()
