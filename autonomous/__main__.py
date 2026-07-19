"""Run ACT or cloud MolmoAct2 autonomous control on two YAM arms."""

from __future__ import annotations

import argparse
import os
import time

import numpy as np

from i2rt.robots.robot import Robot
from autonomous.act_policy import ACTPolicy
from autonomous.control import bounded_action
from autonomous.hardware import CameraRig, open_yam_arms
from autonomous.policies import (
    AutonomousPolicy,
    MolmoAct2CloudPolicy,
    PolicyObservation,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Autonomous bimanual YAM controller")
    parser.add_argument("--policy", choices=("act", "vla"), required=True)
    parser.add_argument(
        "--task", required=True, help="natural-language task instruction"
    )
    parser.add_argument("--left-arm-can", default="can0")
    parser.add_argument("--right-arm-can", default="can1")
    parser.add_argument("--top", required=True, help="top RealSense serial number")
    parser.add_argument("--left", required=True, help="left RealSense serial number")
    parser.add_argument("--right", required=True, help="right RealSense serial number")
    # Match leader_yam_bridge/_v1/camera_dashboard.py dataset capture defaults.
    parser.add_argument("--width", type=int, default=424)
    parser.add_argument("--height", type=int, default=240)
    parser.add_argument("--fps", type=float, default=15.0)
    parser.add_argument(
        "--checkpoint", help="local path or Hub ID for the trained ACT checkpoint"
    )
    parser.add_argument(
        "--device", help="ACT device override, for example cuda, mps, or cpu"
    )
    parser.add_argument("--vla-url", help="MolmoAct2 cloud server base URL")
    parser.add_argument("--vla-token-env", default="YAM_VLA_TOKEN")
    parser.add_argument("--modal-key-env", default="MODAL_PROXY_TOKEN_ID")
    parser.add_argument("--modal-secret-env", default="MODAL_PROXY_TOKEN_SECRET")
    parser.add_argument("--vla-timeout", type=float, default=120.0)
    parser.add_argument(
        "--max-joint-speed", type=float, default=0.5, help="rad/s per arm joint"
    )
    parser.add_argument(
        "--max-gripper-speed", type=float, default=1.0, help="normalized units/s"
    )
    parser.add_argument("--max-steps", type=int, default=0, help="0 runs until Ctrl-C")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="send commands to the arms; without this flag inference is a dry run",
    )
    args = parser.parse_args()
    if args.fps <= 0 or args.max_joint_speed <= 0 or args.max_gripper_speed <= 0:
        parser.error("fps and speed limits must be positive")
    if args.policy == "act" and not args.checkpoint:
        parser.error("--checkpoint is required for --policy act")
    if args.policy == "vla" and not args.vla_url:
        parser.error("--vla-url is required for --policy vla")
    return args


def make_policy(args: argparse.Namespace) -> AutonomousPolicy:
    if args.policy == "act":
        return ACTPolicy(args.checkpoint, device=args.device)
    return MolmoAct2CloudPolicy(
        args.vla_url,
        token=os.environ.get(args.vla_token_env),
        modal_key=os.environ.get(args.modal_key_env),
        modal_secret=os.environ.get(args.modal_secret_env),
        timeout=args.vla_timeout,
    )


def main() -> None:
    args = parse_args()
    policy: AutonomousPolicy | None = None
    cameras: CameraRig | None = None
    arms: list[Robot] = []
    dt = 1.0 / args.fps
    try:
        policy = make_policy(args)
        cameras = CameraRig.open(
            {"top": args.top, "left": args.left, "right": args.right},
            width=args.width,
            height=args.height,
            fps=round(args.fps),
        )
        arms = open_yam_arms(args.left_arm_can, args.right_arm_can)
        if any(arm.num_dofs() != 7 for arm in arms):
            raise RuntimeError(
                "each YAM must expose six arm joints plus one gripper joint"
            )

        mode = "LIVE" if args.execute else "DRY RUN"
        print(
            f"{mode}: {args.policy} policy; Ctrl-C to return both arms to gravity-comp idle"
        )
        step = 0
        policy.reset()
        while args.max_steps <= 0 or step < args.max_steps:
            started = time.monotonic()
            state = np.concatenate(
                [np.asarray(arm.get_joint_pos(), dtype=np.float32)[:7] for arm in arms]
            )
            observation = PolicyObservation(
                state=state, images=cameras.capture(), task=args.task
            )
            target = policy.predict(observation)
            command = bounded_action(
                target,
                state,
                dt=dt,
                max_joint_speed=args.max_joint_speed,
                max_gripper_speed=args.max_gripper_speed,
            )
            if args.execute:
                arms[0].command_joint_pos(command[:7])
                arms[1].command_joint_pos(command[7:])
            else:
                print("action:", np.array2string(command, precision=3), flush=True)
            step += 1
            remaining = dt - (time.monotonic() - started)
            if remaining > 0:
                time.sleep(remaining)
    except KeyboardInterrupt:
        print("\ninterrupted")
    finally:
        for arm in arms:
            try:
                arm.enter_gravity_comp_idle()
            except Exception as exc:
                print(f"arm idle warning: {exc}")
        for arm in arms:
            try:
                arm.close()
            except Exception as exc:
                print(f"arm cleanup warning: {exc}")
        if cameras is not None:
            cameras.close()
        if policy is not None:
            policy.close()


if __name__ == "__main__":
    main()
