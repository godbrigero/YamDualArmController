"""Adapters for the YAM arms and the dashboard's shared-memory snapshots."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Protocol, Sequence

import cv2
import numpy as np

from autonomous.policies import ACTION_DIM, CAMERA_ROLES


SHARED_MEMORY_ROOT = Path("/dev/shm")
CAMERA_SNAPSHOT_NAMES = {
    "top": "cam_top.jpg",
    "left": "cam_wrist_1.jpg",
    "right": "cam_wrist_2.jpg",
}


class YamArm(Protocol):
    def get_joint_pos(self) -> object: ...

    def command_joint_pos(self, positions: object) -> object: ...

    def enter_gravity_comp_idle(self) -> object: ...

    def close(self) -> object: ...

    def num_dofs(self) -> int: ...


class SharedMemoryCameraRig:
    """Read RGB snapshots published by ``_v1/camera_dashboard.py``."""

    def __init__(self, root: Path = SHARED_MEMORY_ROOT) -> None:
        self._root = root

    def capture(self) -> dict[str, np.ndarray]:
        images: dict[str, np.ndarray] = {}
        for role in CAMERA_ROLES:
            path = self._root / CAMERA_SNAPSHOT_NAMES[role]
            try:
                encoded = np.frombuffer(path.read_bytes(), dtype=np.uint8)
            except OSError as exc:
                raise RuntimeError(
                    f"cannot read {role} camera snapshot {path}; start camera_dashboard.py first"
                ) from exc
            bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if bgr is None:
                raise RuntimeError(f"camera snapshot {path} is not a valid JPEG image")
            images[role] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        return images


def read_shared_state(
    channels: Sequence[str], root: Path = SHARED_MEMORY_ROOT
) -> np.ndarray:
    """Read follower state published by teleoperation without opening the arms."""
    values: list[float] = []
    for channel in channels:
        path = root / f"teleop_{channel}.json"
        try:
            with path.open(encoding="utf-8") as stream:
                payload = json.load(stream)
            follower = np.asarray(payload["follower"], dtype=np.float32)
        except (OSError, ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(
                f"cannot read follower state from {path}; run teleoperation for {channel} first"
            ) from exc
        if follower.shape != (7,) or not np.isfinite(follower).all():
            raise RuntimeError(
                f"follower state in {path} must contain 7 finite values; got {follower.shape}"
            )
        values.extend(float(value) for value in follower)

    state = np.asarray(values, dtype=np.float32)
    if state.shape != (ACTION_DIM,):
        raise RuntimeError(
            f"shared follower state must contain {ACTION_DIM} values; got {state.shape}"
        )
    return state


def publish_inference_status(
    action: np.ndarray,
    state: np.ndarray,
    *,
    dry_run: bool,
    root: Path = SHARED_MEMORY_ROOT,
) -> None:
    """Atomically publish the latest inference for the legacy dashboard."""
    path = root / "infer_action.json"
    temporary = root / "infer_action.json.tmp"
    payload = {
        "action": [round(float(value), 4) for value in action],
        "state": [round(float(value), 4) for value in state],
        "dry_run": dry_run,
        "t": time.time(),
    }
    try:
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream)
        os.replace(temporary, path)
    except OSError:
        # Dashboard status must never interrupt robot control.
        pass


def open_yam_arms(channels: Sequence[str]) -> list[YamArm]:
    """Open two YAM arms in training-layout order."""
    from i2rt.robots.get_robot import get_yam_robot
    from i2rt.robots.utils import ArmType, GripperType
    from i2rt.utils.utils import override_log_level

    override_log_level()
    arms: list[YamArm] = []
    try:
        for channel in channels:
            arms.append(
                get_yam_robot(
                    channel=channel,
                    arm_type=ArmType.YAM,
                    gripper_type=GripperType.LINEAR_4310,
                )
            )
    except Exception:
        for arm in arms:
            arm.close()
        raise
    return arms


def read_arm_state(arms: Sequence[YamArm]) -> np.ndarray:
    state = np.concatenate(
        [np.asarray(arm.get_joint_pos(), dtype=np.float32)[:7] for arm in arms]
    )
    if state.shape != (ACTION_DIM,) or not np.isfinite(state).all():
        raise RuntimeError(
            f"YAM state must contain {ACTION_DIM} finite values; got {state.shape}"
        )
    return state
