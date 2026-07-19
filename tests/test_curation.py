"""The triage decision, without winnow in the loop.

`curation.manifest` is deliberately free of rerun and winnow imports: it takes
the two artifacts the pipeline produces and reduces them to a keep list. These
tests pin that reduction, the round trip through curation.json, and the filter
conversion applies.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

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
