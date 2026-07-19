"""Run a local ACT checkpoint on the bimanual YAM rig."""

from __future__ import annotations

import argparse
import time
from collections.abc import Iterable, Sequence

import numpy as np

from autonomous.act_policy import ACTPolicy
from autonomous.control import bounded_action, timed_ramp, velocity_limited_ramp
from autonomous.hardware import (
    SharedMemoryCameraRig,
    YamArm,
    open_yam_arms,
    publish_inference_status,
    read_arm_state,
    read_shared_state,
)
from autonomous.policies import AutonomousPolicy, PolicyObservation


JOINTS_PER_ARM = 7


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous bimanual ACT controller")
    parser.add_argument(
        "--checkpoint",
        required=True,
        help="checkpoint directory, its pretrained_model directory, or a Hub ID",
    )
    parser.add_argument("--channels", default="can0,can1")
    parser.add_argument("--task", default="bimanual teleoperation")
    parser.add_argument("--device", help="ACT device override: cuda, mps, or cpu")
    parser.add_argument("--hz", type=float, default=15.0)
    parser.add_argument(
        "--seconds", type=float, default=0.0, help="0 runs until interrupted"
    )
    parser.add_argument(
        "--engage-vel",
        type=float,
        default=0.4,
        help="maximum value change per second while moving to the first action",
    )
    parser.add_argument(
        "--stream-vel",
        type=float,
        default=1.5,
        help="maximum arm/gripper value change per second while running",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--execute",
        action="store_true",
        help="open and command the arms; the default is a hardware-free dry run",
    )
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="explicitly select the default hardware-free dry-run mode",
    )
    args = parser.parse_args(argv)

    args.channels = [channel.strip() for channel in args.channels.split(",")]
    if len(args.channels) != 2 or any(not channel for channel in args.channels):
        parser.error("--channels must contain exactly two comma-separated CAN channels")
    if len(set(args.channels)) != 2:
        parser.error("--channels must name two different CAN channels")
    if args.hz <= 0 or args.engage_vel <= 0 or args.stream_vel <= 0:
        parser.error("--hz, --engage-vel, and --stream-vel must be positive")
    if args.seconds < 0:
        parser.error("--seconds must be zero or positive")
    return args


def command_arms(arms: Sequence[YamArm], action: np.ndarray) -> None:
    for index, arm in enumerate(arms):
        start = index * JOINTS_PER_ARM
        arm.command_joint_pos(action[start : start + JOINTS_PER_ARM])


def run_ramp(
    arms: Sequence[YamArm], actions: Iterable[np.ndarray], *, dt: float
) -> None:
    for action in actions:
        started = time.monotonic()
        command_arms(arms, action)
        remaining = dt - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    policy: AutonomousPolicy | None = None
    arms: list[YamArm] = []
    cameras = SharedMemoryCameraRig()
    home: np.ndarray | None = None
    home_reset = False
    dt = 1.0 / args.hz

    try:
        policy = ACTPolicy(args.checkpoint, device=args.device)
        if args.execute:
            arms = open_yam_arms(args.channels)
            if any(arm.num_dofs() != JOINTS_PER_ARM for arm in arms):
                raise RuntimeError(
                    "each YAM must expose six arm joints plus one gripper joint"
                )
            read_state = lambda: read_arm_state(arms)
        else:
            read_state = lambda: read_shared_state(args.channels)

        mode = "LIVE" if args.execute else "DRY RUN"
        print(
            f"{mode}: ACT inference at {args.hz:g} Hz; "
            + (
                "Ctrl-C returns both arms home, then to gravity-comp idle"
                if args.execute
                else "reading dashboard/teleop snapshots; no robot hardware is opened"
            ),
            flush=True,
        )

        policy.reset()
        previous_command = read_state()
        home = previous_command.copy()

        if args.execute:
            first_observation = PolicyObservation(
                state=previous_command,
                images=cameras.capture(),
                task=args.task,
            )
            first_action = policy.predict(first_observation)
            print(
                "first action:",
                np.array2string(first_action, precision=2),
                "(moving there slowly)",
                flush=True,
            )
            run_ramp(
                arms,
                velocity_limited_ramp(
                    previous_command,
                    first_action,
                    dt=dt,
                    max_speed=args.engage_vel,
                    minimum_duration=3.0,
                ),
                dt=dt,
            )
            previous_command = first_action

        started_run = time.monotonic()
        frame = 0
        while args.seconds == 0 or time.monotonic() - started_run < args.seconds:
            started_step = time.monotonic()
            state = read_state()
            observation = PolicyObservation(
                state=state,
                images=cameras.capture(),
                task=args.task,
            )
            target = policy.predict(observation)
            command = bounded_action(
                target,
                previous_command,
                dt=dt,
                max_joint_speed=args.stream_vel,
                max_gripper_speed=args.stream_vel,
            )
            publish_inference_status(
                target, state, dry_run=not args.execute
            )
            if args.execute:
                command_arms(arms, command)
                previous_command = command
            elif frame % max(1, round(args.hz)) == 0:
                print(
                    "action=["
                    + " ".join(f"{value:+.2f}" for value in target)
                    + "]",
                    flush=True,
                )

            frame += 1
            remaining = dt - (time.monotonic() - started_step)
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("\ninterrupted", flush=True)
    finally:
        if arms and home is not None:
            try:
                current = read_arm_state(arms)
                run_ramp(
                    arms,
                    timed_ramp(current, home, dt=dt, duration=2.5),
                    dt=dt,
                )
                print("reset to home position.", flush=True)
                home_reset = True
            except Exception as exc:
                print(f"home reset failed: {exc}", flush=True)

        for arm in arms:
            try:
                arm.enter_gravity_comp_idle()
            except Exception as exc:
                print(f"arm idle warning: {exc}", flush=True)
        if arms:
            status = "at home, gravity-comp idle" if home_reset else "gravity-comp idle"
            print(f"YAMs {status}.", flush=True)
        for arm in arms:
            try:
                arm.close()
            except Exception as exc:
                print(f"arm cleanup warning: {exc}", flush=True)
        if policy is not None:
            policy.close()


if __name__ == "__main__":
    main()
