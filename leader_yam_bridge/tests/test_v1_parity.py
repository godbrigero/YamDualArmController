from __future__ import annotations

import importlib.util
import json
import random
import unittest
from pathlib import Path

import numpy as np

from leader_yam_bridge.leader_yam_bridge import (
    DEFAULT_CONFIG_PATH,
    load_bridge_config,
    map_positions,
    normalize_servo_position,
)

ROOT = Path(__file__).resolve().parents[2]
V1_DIR = ROOT / "leader_yam_bridge" / "_v1"
V1_PATH = V1_DIR / "so101_teleop.py"
CALIBRATOR_PATH = V1_DIR / "calibrate_leaders.py"
CALIBRATION_PATH = V1_DIR / "leader_calibration.json"
LEADER_NAMES = ("pan", "lift", "elbow", "wrist_flex", "wrist_roll", "gripper")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class V1ParityTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = load_module("leader_v1_oracle", V1_PATH)
        cls.calibrator = load_module("leader_calibrator", CALIBRATOR_PATH)
        cls.legacy_calibration = json.loads(CALIBRATION_PATH.read_text())

    def test_config_is_an_exact_numeric_copy_of_v1_and_calibration(self) -> None:
        self.assertEqual(tuple(self.calibrator.NAMES), LEADER_NAMES)
        expected_yam_ranges = np.zeros((7, 2), dtype=np.float64)
        for name, index in self.v1.YAM_IDX.items():
            expected_yam_ranges[index] = self.v1.YAM_LIMITS[name]
        expected_yam_ranges[6] = (0.0, 1.0)

        expected_mapping = {
            mapping.leader: (self.v1.YAM_IDX[mapping.yam], mapping.sign)
            for mapping in self.v1.ARM_MAP
        }
        expected_mapping["gripper"] = (6, self.v1.GRIPPER_SIGN)

        for legacy_arm in self.legacy_calibration.values():
            config = load_bridge_config(
                ROOT / DEFAULT_CONFIG_PATH, legacy_arm["serial_id"]
            )
            self.assertEqual(config.yam_ranges.tobytes(), expected_yam_ranges.tobytes())
            self.assertEqual(
                config.leader.fixed_joints,
                ((self.v1.YAM_IDX[self.v1.HELD_JOINT], 0.0),),
            )
            for servo, name in zip(
                config.leader.servos, self.calibrator.NAMES, strict=True
            ):
                self.assertEqual(servo.id, self.calibrator.NAMES.index(name) + 1)
                self.assertEqual(servo.output_range, tuple(legacy_arm["ranges"][name]))
                self.assertEqual((servo.yam_joint, servo.sign), expected_mapping[name])

    def test_normalization_exactly_matches_v1_norm(self) -> None:
        for tick in (-100, 0, 100, 499, 500, 900, 4095):
            for sign in (-1, 1):
                with self.subTest(tick=tick, sign=sign):
                    expected = self.v1.norm(tick, 100, 900, sign)
                    actual = normalize_servo_position(tick, (100, 900), sign)
                    self.assertEqual(actual, expected)

        # Preserve v1's zero-width fallback even though config validation rejects it.
        for sign in (-1, 1):
            self.assertEqual(
                normalize_servo_position(123, (500, 500), sign),
                self.v1.norm(123, 500, 500, sign),
            )

    def test_joint_vectors_are_bit_exact_for_both_leaders(self) -> None:
        for legacy_arm in self.legacy_calibration.values():
            leader_id = legacy_arm["serial_id"]
            config = load_bridge_config(ROOT / DEFAULT_CONFIG_PATH, leader_id)
            ranges = tuple(servo.output_range for servo in config.leader.servos)
            self.v1.LEADER_RANGE = {
                name: output_range
                for name, output_range in zip(LEADER_NAMES, ranges, strict=True)
            }

            for positions in self.position_corpus(ranges):
                ticks = dict(zip(LEADER_NAMES, positions, strict=True))
                expected = self.v1.leader_to_target(ticks)
                actual = map_positions(positions, config)
                self.assertEqual(actual.dtype, expected.dtype)
                self.assertEqual(actual.shape, expected.shape)
                self.assertEqual(
                    actual.tobytes(),
                    expected.tobytes(),
                    msg=f"leader={leader_id}, positions={positions}",
                )

    @staticmethod
    def position_corpus(
        ranges: tuple[tuple[int, int], ...],
    ) -> tuple[tuple[int, ...], ...]:
        lows = tuple(low for low, _ in ranges)
        highs = tuple(high for _, high in ranges)
        mids = tuple((low + high) // 2 for low, high in ranges)
        cases = [lows, highs, mids, (0,) * 6, (4095,) * 6]

        for index, (low, high) in enumerate(ranges):
            for value in (low, high, low - 1, high + 1, 0, 4095):
                pose = list(mids)
                pose[index] = value
                cases.append(tuple(pose))

        random_generator = random.Random(20260719)
        cases.extend(
            tuple(random_generator.randint(0, 4095) for _ in ranges)
            for _ in range(5_000)
        )
        return tuple(cases)


if __name__ == "__main__":
    unittest.main()
