from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from leader_yam_bridge.errors import BridgeConfigError, FeetechError
from leader_yam_bridge.leader_yam_bridge import (
    DEFAULT_BAUD_RATE,
    DEFAULT_POSITION_ADDRESS,
    DEFAULT_POSITION_RANGE,
    DEFAULT_PROTOCOL_END,
    FeetechBus,
    FeetechPortIdentity,
    FeetechServo,
    MissionHacksLeader,
    PortConfig,
    load_bridge_config,
    map_positions,
)

LEADER_ID = "usb-1a86_USB_Single_Serial_TEST-if00"


def valid_config() -> dict[str, object]:
    return {
        "yam_arm": {
            "joint_ranges": {
                "0": [-2.0, 2.0],
                "1": [0.0, 3.0],
                "2": [-1.0, 1.0],
            }
        },
        "leader_arms": {
            LEADER_ID: {
                "port": {},
                "fixed_yam_joints": [{"yam_joint": 1, "position": 1.5}],
                "servos": [
                    {"id": 3, "output_range": [100, 900], "yam_joint": 0, "sign": -1},
                    {"id": 8, "output_range": [200, 1000], "yam_joint": 2, "sign": 1},
                ],
            }
        },
    }


class BridgeTest(unittest.TestCase):
    def load(self, raw: dict[str, object]):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "config.json"
        path.write_text(json.dumps(raw))
        return load_bridge_config(path, LEADER_ID)

    def test_config_is_typed_zero_based_and_uses_hardware_defaults(self) -> None:
        config = self.load(valid_config())
        self.assertFalse(config.yam_ranges.flags.writeable)
        self.assertEqual(config.leader.port, PortConfig())
        self.assertEqual(config.leader.port.baud_rate, DEFAULT_BAUD_RATE)
        self.assertEqual(config.leader.port.protocol_end, DEFAULT_PROTOCOL_END)
        self.assertEqual(config.leader.port.position_address, DEFAULT_POSITION_ADDRESS)
        self.assertEqual(config.leader.port.valid_position_range, DEFAULT_POSITION_RANGE)
        np.testing.assert_array_equal(
            map_positions((100, 1000), config), np.asarray((2.0, 1.5, 1.0))
        )

    def test_invalid_mapping_and_ranges_are_rejected(self) -> None:
        mutations = (
            lambda raw: raw["yam_arm"]["joint_ranges"].pop("1"),
            lambda raw: raw["leader_arms"][LEADER_ID]["servos"][0].__setitem__(
                "output_range", [3, 3]
            ),
            lambda raw: raw["leader_arms"][LEADER_ID]["servos"][0].__setitem__(
                "sign", 0
            ),
            lambda raw: raw["leader_arms"][LEADER_ID]["servos"][1].__setitem__(
                "yam_joint", 0
            ),
            lambda raw: raw["leader_arms"][LEADER_ID]["fixed_yam_joints"][
                0
            ].__setitem__("yam_joint", 0),
        )
        for mutate in mutations:
            raw = copy.deepcopy(valid_config())
            mutate(raw)
            with self.assertRaises(BridgeConfigError):
                self.load(raw)

    def test_port_identity_resolves_all_supported_forms(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        by_id = root / "by-id"
        by_id.mkdir()
        device = root / "ttyACM0"
        device.touch()
        alias = by_id / LEADER_ID
        alias.symlink_to(device)

        for port in (LEADER_ID, alias, device):
            identity = FeetechPortIdentity.resolve(port, by_id)
            self.assertEqual(identity.leader_id, LEADER_ID)
            self.assertEqual(identity.device_path, device.resolve())

    def test_servo_validates_communication_and_raw_position(self) -> None:
        packet = MagicMock()
        packet.read2ByteTxRx.return_value = (2048, 0, 0)
        self.assertEqual(FeetechServo("port", packet, 7).read_position(), 2048)

        for result in ((0, 1, 0), (-1, 0, 0), (4096, 0, 0)):
            packet.read2ByteTxRx.return_value = result
            with self.assertRaises(FeetechError):
                FeetechServo("port", packet, 7).read_position()

    def test_robot_does_not_consume_servo_errors(self) -> None:
        robot = MissionHacksLeader.__new__(MissionHacksLeader)
        failed_servo = MagicMock()
        failed_servo.read_position.side_effect = FeetechError("read failed")
        robot._servos = (failed_servo,)

        with self.assertRaisesRegex(FeetechError, "read failed"):
            robot.get_joint_pos()

    def test_bus_uses_proven_sdk_defaults_and_cleans_up_failure(self) -> None:
        identity = FeetechPortIdentity(Path("/tmp/ttyACM-test"), LEADER_ID)
        port = MagicMock()
        port.openPort.return_value = True
        port.setBaudRate.return_value = True
        with (
            patch("leader_yam_bridge.leader_yam_bridge.PortHandler", return_value=port),
            patch("leader_yam_bridge.leader_yam_bridge.PacketHandler") as packet,
        ):
            bus = FeetechBus(identity, PortConfig())
            port.setBaudRate.assert_called_once_with(1_000_000)
            packet.assert_called_once_with(0)
            bus.close()

        failed_port = MagicMock()
        failed_port.openPort.return_value = True
        failed_port.setBaudRate.return_value = False
        with patch(
            "leader_yam_bridge.leader_yam_bridge.PortHandler",
            return_value=failed_port,
        ):
            with self.assertRaises(FeetechError):
                FeetechBus(identity, PortConfig())
        failed_port.closePort.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
