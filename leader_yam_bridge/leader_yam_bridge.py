from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from i2rt.robots.robot import Robot
from numpy.typing import NDArray
from scservo_sdk import PacketHandler, PortHandler

from .errors import BridgeConfigError, FeetechError

FloatArray = NDArray[np.float64]

DEFAULT_CONFIG_PATH = Path("outputs/mission_hacks_calibrations.json")
DEFAULT_BY_ID_DIRECTORY = Path("/dev/serial/by-id")
DEFAULT_BAUD_RATE = 1_000_000
DEFAULT_PROTOCOL_END = 0
DEFAULT_POSITION_ADDRESS = 56
DEFAULT_POSITION_RANGE = (0, 4095)


@dataclass(frozen=True)
class PortConfig:
    baud_rate: int = DEFAULT_BAUD_RATE
    protocol_end: int = DEFAULT_PROTOCOL_END
    position_address: int = DEFAULT_POSITION_ADDRESS
    valid_position_range: tuple[int, int] = DEFAULT_POSITION_RANGE


@dataclass(frozen=True)
class ServoConfig:
    id: int
    output_range: tuple[int, int]
    yam_joint: int
    sign: int


@dataclass(frozen=True)
class LeaderConfig:
    port: PortConfig
    servos: tuple[ServoConfig, ...]
    fixed_joints: tuple[tuple[int, float], ...]


@dataclass(frozen=True)
class BridgeConfig:
    yam_ranges: FloatArray
    leader: LeaderConfig


@dataclass(frozen=True)
class FeetechPortIdentity:
    device_path: Path
    leader_id: str

    @classmethod
    def resolve(
        cls,
        port: str | Path,
        by_id_directory: Path = DEFAULT_BY_ID_DIRECTORY,
    ) -> FeetechPortIdentity:
        requested = Path(port)
        by_id_directory = Path(by_id_directory)
        if not by_id_directory.is_dir():
            raise FeetechError(f"Serial identity directory not found: {by_id_directory}")

        if requested.parent == Path("."):
            alias = by_id_directory / requested.name
            if not alias.exists():
                raise FeetechError(f"Unknown serial controller: {requested.name}")
            return cls(alias.resolve(), requested.name)

        try:
            device_path = requested.resolve(strict=True)
        except FileNotFoundError as exc:
            raise FeetechError(f"Serial device not found: {requested}") from exc

        if requested.parent.resolve() == by_id_directory.resolve():
            return cls(device_path, requested.name)

        for alias in sorted(by_id_directory.iterdir()):
            if alias.resolve(strict=True) == device_path:
                return cls(device_path, alias.name)
        raise FeetechError(f"No stable serial identity points to {requested}")


def normalize_servo_position(
    tick: float,
    output_range: tuple[int, int],
    sign: int,
) -> float:
    """Mirror of _v1.norm with the range grouped by ServoConfig."""
    lo, hi = output_range
    n = (tick - lo) / (hi - lo) if hi != lo else 0.0
    n = min(1.0, max(0.0, n))
    return (1.0 - n) if sign < 0 else n


def map_positions(positions: Sequence[int], config: BridgeConfig) -> FloatArray:
    if len(positions) != len(config.leader.servos):
        raise ValueError(
            f"Expected {len(config.leader.servos)} servo positions, got {len(positions)}"
        )

    # This deliberately mirrors _v1.leader_to_target's math and assignment order.
    q = np.zeros(len(config.yam_ranges))
    for servo, tick in zip(config.leader.servos, positions, strict=True):
        llo, lhi = servo.output_range
        n = normalize_servo_position(tick, (llo, lhi), servo.sign)
        ylo, yhi = config.yam_ranges[servo.yam_joint]
        q[servo.yam_joint] = ylo + n * (yhi - ylo)
    for yam_joint, position in config.leader.fixed_joints:
        q[yam_joint] = position
    return q


class FeetechServo:
    def __init__(
        self,
        port_handler: Any,
        packet_handler: Any,
        servo_id: int,
        position_address: int = DEFAULT_POSITION_ADDRESS,
        valid_position_range: tuple[int, int] = DEFAULT_POSITION_RANGE,
    ):
        self._port = port_handler
        self._packet = packet_handler
        self._address = position_address
        self._valid_range = valid_position_range
        self.id = servo_id

    def read_position(self) -> int:
        raw, comm, error = self._packet.read2ByteTxRx(
            self._port, self.id, self._address
        )
        if comm != 0:
            raise FeetechError(
                f"Servo {self.id} communication failed (comm={comm}, error={error})"
            )
        low, high = self._valid_range
        if not low <= raw <= high:
            raise FeetechError(
                f"Servo {self.id} returned {raw}; expected {low}..{high}"
            )
        return int(raw)


class FeetechBus:
    def __init__(self, identity: FeetechPortIdentity, config: PortConfig):
        self._closed = False
        self._port = PortHandler(str(identity.device_path))
        if not self._port.openPort():
            raise FeetechError(f"Could not open {identity.device_path}")
        if not self._port.setBaudRate(config.baud_rate):
            self._port.closePort()
            self._closed = True
            raise FeetechError(f"Could not set baud rate to {config.baud_rate}")
        try:
            self._packet = PacketHandler(config.protocol_end)
        except Exception:
            self._port.closePort()
            self._closed = True
            raise
        self._address = config.position_address
        self._valid_range = config.valid_position_range

    def create_servo(self, servo_id: int) -> FeetechServo:
        return FeetechServo(
            self._port,
            self._packet,
            servo_id,
            self._address,
            self._valid_range,
        )

    def ping(self, servo_id: int) -> bool:
        return self._packet.ping(self._port, servo_id)[1] == 0

    def close(self) -> None:
        if not self._closed:
            self._closed = True
            self._port.closePort()


def _pair(value: Any, kind: type[int] | type[float]) -> tuple[Any, Any]:
    if not isinstance(value, list) or len(value) != 2:
        raise BridgeConfigError("Expected a two-value range")
    return kind(value[0]), kind(value[1])


def _validate_config(config: BridgeConfig) -> None:
    ranges = config.yam_ranges
    if ranges.ndim != 2 or ranges.shape[1] != 2 or not len(ranges):
        raise BridgeConfigError("YAM joint ranges must have shape (N, 2)")
    if not np.isfinite(ranges).all() or np.any(ranges[:, 0] == ranges[:, 1]):
        raise BridgeConfigError("YAM joint ranges must be finite and non-zero")

    port = config.leader.port
    if port.baud_rate <= 0 or port.protocol_end not in (0, 1):
        raise BridgeConfigError("Invalid port configuration")
    if port.position_address < 0 or port.valid_position_range[0] >= port.valid_position_range[1]:
        raise BridgeConfigError("Invalid position register configuration")

    servo_ids: set[int] = set()
    mapped_joints: set[int] = set()
    for servo in config.leader.servos:
        if servo.id <= 0 or servo.id in servo_ids:
            raise BridgeConfigError("Servo IDs must be unique and positive")
        if servo.output_range[0] >= servo.output_range[1]:
            raise BridgeConfigError(f"Servo {servo.id} has an invalid output range")
        if servo.sign not in (-1, 1) or not 0 <= servo.yam_joint < len(ranges):
            raise BridgeConfigError(f"Servo {servo.id} has an invalid YAM mapping")
        if servo.yam_joint in mapped_joints:
            raise BridgeConfigError("Multiple servos map to one YAM joint")
        servo_ids.add(servo.id)
        mapped_joints.add(servo.yam_joint)

    fixed_joints: set[int] = set()
    for joint, position in config.leader.fixed_joints:
        if joint in fixed_joints or not 0 <= joint < len(ranges):
            raise BridgeConfigError("Invalid fixed YAM joint")
        low, high = ranges[joint]
        if not min(low, high) <= position <= max(low, high):
            raise BridgeConfigError("Fixed position is outside its YAM range")
        fixed_joints.add(joint)

    if mapped_joints & fixed_joints:
        raise BridgeConfigError("A YAM joint cannot be both mapped and fixed")
    if mapped_joints | fixed_joints != set(range(len(ranges))):
        raise BridgeConfigError("Every YAM joint must be mapped or fixed")


def load_bridge_config(path: str | Path, leader_id: str) -> BridgeConfig:
    try:
        raw: dict[str, Any] = json.loads(Path(path).read_text())
        range_map: dict[str, Any] = raw["yam_arm"]["joint_ranges"]
        expected_keys = {str(index) for index in range(len(range_map))}
        if set(range_map) != expected_keys:
            raise BridgeConfigError("YAM joint IDs must be contiguous from 0")

        ranges = np.asarray(
            [_pair(range_map[str(index)], float) for index in range(len(range_map))],
            dtype=np.float64,
        )
        ranges.setflags(write=False)

        arm: dict[str, Any] = raw["leader_arms"][leader_id]
        port_data: dict[str, Any] = arm.get("port", {})
        port = PortConfig(
            baud_rate=int(port_data.get("baud_rate", DEFAULT_BAUD_RATE)),
            protocol_end=int(port_data.get("protocol_end", DEFAULT_PROTOCOL_END)),
            position_address=int(
                port_data.get("position_address", DEFAULT_POSITION_ADDRESS)
            ),
            valid_position_range=_pair(
                port_data.get("valid_position_range", list(DEFAULT_POSITION_RANGE)), int
            ),
        )
        servos = tuple(
            ServoConfig(
                id=int(servo["id"]),
                output_range=_pair(servo["output_range"], int),
                yam_joint=int(servo["yam_joint"]),
                sign=int(servo["sign"]),
            )
            for servo in arm["servos"]
        )
        fixed_joints = tuple(
            (int(fixed["yam_joint"]), float(fixed["position"]))
            for fixed in arm.get("fixed_yam_joints", [])
        )
    except BridgeConfigError:
        raise
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise BridgeConfigError(f"Invalid leader config: {exc}") from exc

    config = BridgeConfig(ranges, LeaderConfig(port, servos, fixed_joints))
    _validate_config(config)
    return config


class MissionHacksLeader(Robot):
    def __init__(
        self,
        port: str | Path,
        config_file: Path | None = None,
        *,
        by_id_directory: Path = DEFAULT_BY_ID_DIRECTORY,
    ):
        self.identity = FeetechPortIdentity.resolve(port, by_id_directory)
        self.config_path = Path(config_file or DEFAULT_CONFIG_PATH)
        self._config = load_bridge_config(self.config_path, self.identity.leader_id)
        self._bus = FeetechBus(self.identity, self._config.leader.port)
        self._servos = tuple(
            self._bus.create_servo(servo.id) for servo in self._config.leader.servos
        )

    def get_joint_pos(self) -> FloatArray:
        positions = tuple(servo.read_position() for servo in self._servos)
        return map_positions(positions, self._config)

    def close(self) -> None:
        self._bus.close()

    def num_dofs(self) -> int:
        return len(self._config.yam_ranges)

    def get_observations(self) -> dict[str, FloatArray]:
        return {
            "joint_pos": self.get_joint_pos(),
            "joint_vel": np.zeros(self.num_dofs(), dtype=np.float64),
        }

    def enter_gravity_comp_idle(self) -> None:
        pass


def get_mission_hacks_leader(
    port: str | Path,
    config_file: Path | None = None,
) -> MissionHacksLeader:
    return MissionHacksLeader(port, config_file)
