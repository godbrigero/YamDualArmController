from __future__ import annotations

import copy
import importlib.util
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from leader_yam_bridge.errors import BridgeConfigError, FeetechError
from leader_yam_bridge.leader_yam_bridge import (
    DEFAULT_CONFIG_PATH,
    FeetechPortIdentity,
    FeetechServo,
    load_bridge_config,
)
from scripts import calibration

LEADER_A = "usb-1a86_USB_Single_Serial_A-if00"
LEADER_B = "usb-1a86_USB_Single_Serial_B-if00"
V1_CALIBRATOR = Path(__file__).resolve().parents[1] / "_v1" / "calibrate_leaders.py"


def load_v1_calibrator():
    spec = importlib.util.spec_from_file_location("v1_calibrator_oracle", V1_CALIBRATOR)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {V1_CALIBRATOR}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def bridge_config() -> dict[str, object]:
    arm = {
        "calibrated_at": "old",
        "port": {
            "baud_rate": 1_000_000,
            "protocol_end": 0,
            "position_address": 56,
            "valid_position_range": [0, 4095],
        },
        "fixed_yam_joints": [{"yam_joint": 4, "position": 0.0}],
        "servos": [
            {"id": 1, "output_range": [10, 100], "yam_joint": 0, "sign": -1},
            {"id": 2, "output_range": [20, 200], "yam_joint": 1, "sign": 1},
            {"id": 3, "output_range": [30, 300], "yam_joint": 2, "sign": -1},
            {"id": 4, "output_range": [40, 400], "yam_joint": 3, "sign": -1},
            {"id": 5, "output_range": [50, 500], "yam_joint": 5, "sign": -1},
            {"id": 6, "output_range": [60, 600], "yam_joint": 6, "sign": 1},
        ],
    }
    return {
        "yam_arm": {
            "joint_ranges": {
                "0": [-2.61799, 3.05433],
                "1": [0.0, 3.65],
                "2": [0.0, 3.66519],
                "3": [-1.5708, 1.5708],
                "4": [-1.5708, 1.5708],
                "5": [-2.0944, 2.0944],
                "6": [0.0, 1.0],
            }
        },
        "leader_arms": {LEADER_A: arm},
    }


def sweep_state(leader_id: str = LEADER_A) -> calibration.SweepState:
    lows = [101, 202, 303, 404, 505, 606]
    highs = [1001, 1202, 1303, 1404, 1505, 1606]
    return calibration.SweepState(
        leader_id=leader_id,
        servo_ids=(1, 2, 3, 4, 5, 6),
        positions=lows.copy(),
        minimums=lows,
        maximums=highs,
    )


def fake_session(leader_id: str) -> calibration.ControllerSession:
    servos = tuple(MagicMock(id=servo_id) for servo_id in range(1, 7))
    return calibration.ControllerSession(
        FeetechPortIdentity(Path(f"/dev/{leader_id}"), leader_id),
        MagicMock(),
        servos,
    )


class CalibrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.v1 = load_v1_calibrator()

    def test_default_output_is_the_bridge_config_file(self) -> None:
        self.assertEqual(calibration.parse_args([]).config_file, DEFAULT_CONFIG_PATH)

    def test_update_changes_only_ranges_and_calibration_time(self) -> None:
        raw = bridge_config()
        before = copy.deepcopy(raw)

        with patch.object(calibration, "datetime") as clock:
            clock.now.return_value.isoformat.return_value = "2026-07-19T12:00:00"
            calibration.update_config(raw, (sweep_state(),), minimum_span=50)

        old_arm = before["leader_arms"][LEADER_A]
        new_arm = raw["leader_arms"][LEADER_A]
        self.assertEqual(new_arm["port"], old_arm["port"])
        self.assertEqual(new_arm["fixed_yam_joints"], old_arm["fixed_yam_joints"])
        self.assertEqual(raw["yam_arm"], before["yam_arm"])
        self.assertEqual(new_arm["calibrated_at"], "2026-07-19T12:00:00")

        expected_ranges = [
            [101, 1001],
            [202, 1202],
            [303, 1303],
            [404, 1404],
            [505, 1505],
            [606, 1606],
        ]
        for old_servo, new_servo, expected_range in zip(
            old_arm["servos"], new_arm["servos"], expected_ranges, strict=True
        ):
            self.assertEqual(new_servo["output_range"], expected_range)
            self.assertEqual(new_servo["id"], old_servo["id"])
            self.assertEqual(new_servo["yam_joint"], old_servo["yam_joint"])
            self.assertEqual(new_servo["sign"], old_servo["sign"])

    def test_save_validates_then_atomically_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / DEFAULT_CONFIG_PATH.name
            path.write_text("existing calibration\n")
            raw = bridge_config()
            calibration.update_config(raw, (sweep_state(),), minimum_span=50)
            real_replace = os.replace

            def replace_after_check(source: Path, destination: Path) -> None:
                self.assertEqual(destination.read_text(), "existing calibration\n")
                real_replace(source, destination)

            with patch.object(calibration.os, "replace", side_effect=replace_after_check):
                calibration.save_config(path, raw)

            self.assertEqual(json.loads(path.read_text()), raw)
            load_bridge_config(path, LEADER_A)
            self.assertFalse((path.parent / f".{path.name}.tmp").exists())

    def test_failed_validation_never_replaces_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / DEFAULT_CONFIG_PATH.name
            original = b"existing calibration stays byte-for-byte unchanged\n"
            path.write_bytes(original)
            raw = bridge_config()
            raw["leader_arms"][LEADER_A]["servos"][0]["sign"] = 0

            with self.assertRaises(BridgeConfigError):
                calibration.save_config(path, raw)

            self.assertEqual(path.read_bytes(), original)
            self.assertFalse((path.parent / f".{path.name}.tmp").exists())

    def test_health_checks_multiple_controllers_concurrently(self) -> None:
        sessions = (fake_session(LEADER_A), fake_session(LEADER_B))
        rendezvous = threading.Barrier(2)

        def checked(session, pings):
            rendezvous.wait(timeout=1)
            return session, (pings,) * 6

        with (
            patch.object(calibration, "health_check", side_effect=checked),
            patch("builtins.print"),
        ):
            calibration.run_health_checks(sessions, pings=3)

    def test_controller_errors_are_not_consumed(self) -> None:
        sessions = (fake_session(LEADER_A), fake_session(LEADER_B))
        with (
            patch.object(
                calibration,
                "health_check",
                side_effect=FeetechError("controller failed"),
            ),
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(FeetechError, "controller failed"):
                calibration.run_health_checks(sessions, pings=3)

    def test_stable_initial_read_is_identical_to_v1(self) -> None:
        readings = (1000, 1004, 998, 1400, 1002)
        v1_packet = MagicMock()
        v1_packet.read2ByteTxRx.side_effect = [
            (position, 0, 0) for position in readings
        ]
        expected = self.v1.robust_read(v1_packet, "port", 1)

        new_packet = MagicMock()
        new_packet.read2ByteTxRx.side_effect = [
            (position, 0, 0) for position in readings
        ]
        actual = calibration.robust_position(
            FeetechServo("port", new_packet, servo_id=1)
        )
        self.assertEqual(actual, expected)

    def test_calculation_error_prevents_the_final_save(self) -> None:
        raw = bridge_config()
        raw["leader_arms"][LEADER_B] = copy.deepcopy(
            raw["leader_arms"][LEADER_A]
        )
        identities = (
            FeetechPortIdentity(Path("/dev/a"), LEADER_A),
            FeetechPortIdentity(Path("/dev/b"), LEADER_B),
        )
        sessions = (fake_session(LEADER_A), fake_session(LEADER_B))
        incomplete = sweep_state(LEADER_B)
        incomplete.maximums = incomplete.minimums.copy()

        with (
            patch.object(calibration, "load_raw_config", return_value=raw),
            patch.object(calibration, "resolve_identities", return_value=identities),
            patch.object(calibration, "open_sessions", return_value=sessions),
            patch.object(calibration, "run_health_checks"),
            patch.object(
                calibration,
                "run_sweep",
                return_value=(sweep_state(), incomplete),
            ),
            patch.object(calibration, "save_config") as save,
            patch.object(calibration, "close_sessions") as close,
            patch("builtins.print"),
        ):
            with self.assertRaisesRegex(RuntimeError, "incomplete"):
                calibration.main(["--yes"])

        save.assert_not_called()
        close.assert_called_once_with(sessions)


if __name__ == "__main__":
    unittest.main()
