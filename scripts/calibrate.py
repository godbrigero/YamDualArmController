from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from leader_yam_bridge.leader_yam_bridge import (
    DEFAULT_BAUD_RATE,
    DEFAULT_BY_ID_DIRECTORY,
    DEFAULT_CONFIG_PATH,
    DEFAULT_POSITION_ADDRESS,
    DEFAULT_POSITION_RANGE,
    DEFAULT_PROTOCOL_END,
    FeetechBus,
    FeetechPortIdentity,
    FeetechServo,
    PortConfig,
    load_bridge_config,
)

CONTROLLER_PREFIX = "usb-1a86_USB_Single_Serial_"


@dataclass(frozen=True)
class ControllerSession:
    identity: FeetechPortIdentity
    bus: FeetechBus
    servos: tuple[FeetechServo, ...]

    @property
    def servo_ids(self) -> tuple[int, ...]:
        return tuple(servo.id for servo in self.servos)


@dataclass
class SweepState:
    leader_id: str
    servo_ids: tuple[int, ...]
    positions: list[int]
    minimums: list[int]
    maximums: list[int]
    lock: threading.Lock = field(default_factory=threading.Lock)

    def update(self, index: int, position: int) -> None:
        with self.lock:
            self.positions[index] = position
            self.minimums[index] = min(self.minimums[index], position)
            self.maximums[index] = max(self.maximums[index], position)

    def snapshot(self) -> tuple[tuple[int, int, int, int], ...]:
        with self.lock:
            return tuple(
                (servo_id, position, low, high)
                for servo_id, position, low, high in zip(
                    self.servo_ids,
                    self.positions,
                    self.minimums,
                    self.maximums,
                    strict=True,
                )
            )

    def output_ranges(self, minimum_span: int) -> tuple[tuple[int, int, int], ...]:
        result = tuple(
            (servo_id, low, high)
            for servo_id, _, low, high in self.snapshot()
        )
        too_small = [
            (servo_id, high - low)
            for servo_id, low, high in result
            if high - low < minimum_span
        ]
        if too_small:
            details = ", ".join(
                f"servo {servo_id}: span {span}" for servo_id, span in too_small
            )
            raise RuntimeError(
                f"Calibration for {self.leader_id} is incomplete ({details})"
            )
        return result


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Health-check and calibrate one or more SO-101 leaders concurrently. "
            "With no --port, every connected 1a86 USB controller is selected."
        )
    )
    parser.add_argument(
        "--port",
        action="append",
        dest="ports",
        help=(
            "Calibrate only this device. May be repeated. Accepts /dev/ttyACM*, "
            "/dev/serial/by-id/*, or a by-id basename."
        ),
    )
    parser.add_argument(
        "--config-file",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=f"Bridge configuration to update (default: {DEFAULT_CONFIG_PATH})",
    )
    parser.add_argument("--pings", type=int, default=15)
    parser.add_argument(
        "--minimum-span",
        type=int,
        default=50,
        help="Minimum captured tick span required for every servo.",
    )
    parser.add_argument(
        "--template-leader",
        help=(
            "Existing leader ID whose port settings and servo mappings should be "
            "copied when a newly connected leader is not yet in the config."
        ),
    )
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--show", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation.")
    return parser.parse_args(argv)


def discover_ports(
    by_id_directory: Path = DEFAULT_BY_ID_DIRECTORY,
) -> tuple[Path, ...]:
    if not by_id_directory.is_dir():
        raise RuntimeError(f"Serial identity directory not found: {by_id_directory}")
    ports = tuple(
        path
        for path in sorted(by_id_directory.iterdir())
        if path.name.startswith(CONTROLLER_PREFIX) and path.exists()
    )
    if not ports:
        raise RuntimeError(
            f"No {CONTROLLER_PREFIX}* controllers found in {by_id_directory}"
        )
    return ports


def resolve_identities(
    ports: list[str] | tuple[Path, ...] | None,
    by_id_directory: Path = DEFAULT_BY_ID_DIRECTORY,
) -> tuple[FeetechPortIdentity, ...]:
    selected = ports if ports else discover_ports(by_id_directory)
    identities = tuple(
        FeetechPortIdentity.resolve(port, by_id_directory) for port in selected
    )
    leader_ids = tuple(identity.leader_id for identity in identities)
    if len(set(leader_ids)) != len(leader_ids):
        raise RuntimeError("The same controller was selected more than once")
    return identities


def load_raw_config(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"Bridge configuration not found: {path}")
    raw = json.loads(path.read_text())
    if "yam_arm" not in raw or "leader_arms" not in raw:
        raise RuntimeError(f"Not a bridge configuration: {path}")
    return raw


def add_missing_leaders(
    raw: dict[str, Any],
    identities: tuple[FeetechPortIdentity, ...],
    template_leader: str | None,
) -> None:
    leader_arms = raw["leader_arms"]
    missing = [
        identity.leader_id
        for identity in identities
        if identity.leader_id not in leader_arms
    ]
    if not missing:
        return
    if template_leader is None:
        raise RuntimeError(
            "New leader(s) require --template-leader so servo signs and YAM "
            f"mappings are explicit: {', '.join(missing)}"
        )
    if template_leader not in leader_arms:
        raise RuntimeError(f"Template leader is not configured: {template_leader}")

    for leader_id in missing:
        leader_arms[leader_id] = copy.deepcopy(leader_arms[template_leader])
        leader_arms[leader_id].pop("calibrated_at", None)


def port_config(raw_arm: dict[str, Any]) -> PortConfig:
    raw = raw_arm.get("port", {})
    position_low, position_high = raw.get(
        "valid_position_range", DEFAULT_POSITION_RANGE
    )
    return PortConfig(
        baud_rate=int(raw.get("baud_rate", DEFAULT_BAUD_RATE)),
        protocol_end=int(raw.get("protocol_end", DEFAULT_PROTOCOL_END)),
        position_address=int(raw.get("position_address", DEFAULT_POSITION_ADDRESS)),
        valid_position_range=(int(position_low), int(position_high)),
    )


def open_sessions(
    identities: tuple[FeetechPortIdentity, ...],
    raw: dict[str, Any],
) -> tuple[ControllerSession, ...]:
    sessions: list[ControllerSession] = []
    try:
        for identity in identities:
            arm = raw["leader_arms"][identity.leader_id]
            bus = FeetechBus(identity, port_config(arm))
            servos = tuple(
                bus.create_servo(int(servo["id"])) for servo in arm["servos"]
            )
            sessions.append(ControllerSession(identity, bus, servos))
    except Exception:
        for session in sessions:
            session.bus.close()
        raise
    return tuple(sessions)


def close_sessions(sessions: tuple[ControllerSession, ...]) -> None:
    for session in sessions:
        session.bus.close()


def health_check(
    session: ControllerSession,
    pings: int,
) -> tuple[ControllerSession, tuple[int, ...]]:
    counts = [0] * len(session.servos)
    for _ in range(pings):
        for index, servo in enumerate(session.servos):
            if session.bus.ping(servo.id):
                counts[index] += 1
        time.sleep(0.2)
    return session, tuple(counts)


def run_health_checks(
    sessions: tuple[ControllerSession, ...],
    pings: int,
) -> None:
    print(f"\n[health] Pinging every servo {pings} times in parallel...")
    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        results = tuple(executor.map(lambda session: health_check(session, pings), sessions))

    failed: list[str] = []
    for session, counts in results:
        print(f"\n  {session.identity.leader_id}")
        for servo_id, count in zip(session.servo_ids, counts, strict=True):
            status = "OK" if count == pings else "FAIL"
            print(f"    servo {servo_id:2d}: {count:2d}/{pings}  {status}")
        if any(count != pings for count in counts):
            failed.append(session.identity.leader_id)
    if failed:
        raise RuntimeError(f"Health check failed: {', '.join(failed)}")
    print("\n[health] All controllers and servos are stable.")


def robust_position(servo: FeetechServo) -> int:
    values = sorted(servo.read_position() for _ in range(5))
    median = values[len(values) // 2]
    close = [value for value in values if abs(value - median) <= 40]
    if len(close) < 3:
        raise RuntimeError(f"Servo {servo.id} did not produce a stable initial reading")
    return sum(close) // len(close)


def initialize_sweep(session: ControllerSession) -> SweepState:
    positions = [robust_position(servo) for servo in session.servos]
    return SweepState(
        session.identity.leader_id,
        session.servo_ids,
        positions.copy(),
        positions.copy(),
        positions.copy(),
    )


def capture(
    session: ControllerSession,
    state: SweepState,
    stop: threading.Event,
) -> None:
    while not stop.is_set():
        for index, servo in enumerate(session.servos):
            state.update(index, servo.read_position())
        time.sleep(0.01)


def render(states: tuple[SweepState, ...], elapsed: float) -> list[str]:
    lines = [f"[capture] elapsed {elapsed:6.1f}s — Ctrl-C when every joint is swept"]
    for state in states:
        lines.append(f"  {state.leader_id}")
        lines.append("    SERVO    CURRENT      MIN      MAX     SPAN")
        for servo_id, position, low, high in state.snapshot():
            lines.append(
                f"    {servo_id:5d}    {position:7d}  {low:7d}  {high:7d}  {high-low:7d}"
            )
    return lines


def print_live(lines: list[str], previous_line_count: int) -> int:
    if previous_line_count and sys.stdout.isatty():
        print(f"\033[{previous_line_count}A", end="")
    print("".join(f"\033[2K{line}\n" for line in lines), end="", flush=True)
    return len(lines)


def run_sweep(sessions: tuple[ControllerSession, ...]) -> tuple[SweepState, ...]:
    print("\n[calibration] Taking stable initial readings...")
    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        states = tuple(executor.map(initialize_sweep, sessions))

    input(
        "\nPress ENTER to begin. Sweep EVERY joint and gripper on ALL leaders "
        "through both extremes, then press Ctrl-C to finish..."
    )
    stop = threading.Event()
    previous_line_count = 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=len(sessions)) as executor:
        futures: tuple[Future[None], ...] = tuple(
            executor.submit(capture, session, state, stop)
            for session, state in zip(sessions, states, strict=True)
        )
        try:
            while True:
                for future in futures:
                    if future.done():
                        future.result()
                previous_line_count = print_live(
                    render(states, time.monotonic() - start), previous_line_count
                )
                time.sleep(0.1)
        except KeyboardInterrupt:
            stop.set()
        finally:
            stop.set()
        for future in futures:
            future.result()
    print()
    return states


def update_config(
    raw: dict[str, Any],
    states: tuple[SweepState, ...],
    minimum_span: int,
) -> None:
    timestamp = datetime.now().isoformat(timespec="seconds")
    for state in states:
        arm = raw["leader_arms"][state.leader_id]
        output_ranges = {
            servo_id: [low, high]
            for servo_id, low, high in state.output_ranges(minimum_span)
        }
        for servo in arm["servos"]:
            servo["output_range"] = output_ranges[int(servo["id"])]
        arm["calibrated_at"] = timestamp


def save_config(
    path: Path,
    raw: dict[str, Any],
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(json.dumps(raw, indent=2) + "\n")
        for leader_id in raw["leader_arms"]:
            load_bridge_config(temporary, leader_id)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def show_config(path: Path, raw: dict[str, Any]) -> None:
    print(f"Configuration: {path}")
    print("\nYAM joint ranges:")
    for joint, limits in raw["yam_arm"]["joint_ranges"].items():
        print(f"  joint {joint}: {limits[0]:+.5f} .. {limits[1]:+.5f}")
    print("\nLeader arms:")
    for leader_id, arm in raw["leader_arms"].items():
        print(f"  {leader_id}  calibrated_at={arm.get('calibrated_at', 'never')}")
        for servo in arm["servos"]:
            low, high = servo["output_range"]
            print(
                f"    servo {servo['id']}: ticks {low}..{high}, "
                f"YAM {servo['yam_joint']}, sign {servo['sign']:+d}"
            )


def print_selection(identities: tuple[FeetechPortIdentity, ...]) -> None:
    print("=" * 78)
    print("SO-101 LEADER CALIBRATION")
    print("=" * 78)
    print(f"Selected {len(identities)} controller(s):")
    for identity in identities:
        print(f"  {identity.leader_id}\n    device: {identity.device_path}")


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    raw = load_raw_config(args.config_file)
    if args.show:
        show_config(args.config_file, raw)
        return
    if args.pings <= 0 or args.minimum_span <= 0:
        raise ValueError("--pings and --minimum-span must be positive")

    identities = resolve_identities(args.ports)
    print_selection(identities)
    add_missing_leaders(raw, identities, args.template_leader)

    if not args.yes:
        answer = input("\nContinue with these controllers? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            print("Cancelled; configuration was not changed.")
            return

    sessions = open_sessions(identities, raw)
    try:
        run_health_checks(sessions, args.pings)
        if args.check_only:
            print("\nCheck-only complete; configuration was not changed.")
            return
        states = run_sweep(sessions)
        update_config(raw, states, args.minimum_span)
        save_config(args.config_file, raw)
        print(f"\nSaved calibration atomically to {args.config_file}")
        show_config(args.config_file, raw)
    finally:
        close_sessions(sessions)


if __name__ == "__main__":
    main()
