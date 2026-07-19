"""YAM and RealSense hardware adapters.

This module intentionally imports its hardware dependencies normally at module
scope. Import it only on the robot computer where i2rt and pyrealsense2 exist.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pyrealsense2 as rs
from i2rt.robots.get_robot import get_yam_robot
from i2rt.robots.utils import ArmType, GripperType


@dataclass
class CameraRig:
    pipelines: dict[str, rs.pipeline]

    @classmethod
    def open(
        cls,
        serials: dict[str, str],
        *,
        width: int,
        height: int,
        fps: int,
    ) -> "CameraRig":
        pipelines: dict[str, rs.pipeline] = {}
        try:
            for role, serial in serials.items():
                pipeline = rs.pipeline()
                config = rs.config()
                config.enable_device(serial)
                config.enable_stream(rs.stream.color, width, height, rs.format.rgb8, fps)
                pipeline.start(config)
                for _ in range(5):
                    pipeline.wait_for_frames(timeout_ms=2000)
                pipelines[role] = pipeline
                print(f"camera {role}: {serial} ({width}x{height}@{fps})")
        except Exception:
            for pipeline in pipelines.values():
                pipeline.stop()
            raise
        return cls(pipelines)

    def capture(self, timeout_ms: int = 2000) -> dict[str, np.ndarray]:
        images: dict[str, np.ndarray] = {}
        for role, pipeline in self.pipelines.items():
            frames = pipeline.wait_for_frames(timeout_ms=timeout_ms)
            color = frames.get_color_frame()
            if not color:
                raise RuntimeError(f"camera {role} returned no RGB frame")
            images[role] = np.asanyarray(color.get_data()).copy()
        return images

    def close(self) -> None:
        for pipeline in self.pipelines.values():
            try:
                pipeline.stop()
            except Exception as exc:
                print(f"camera cleanup warning: {exc}")


def open_yam_arms(left_channel: str, right_channel: str) -> list[object]:
    return [
        get_yam_robot(
            channel=channel,
            arm_type=ArmType.YAM,
            gripper_type=GripperType.LINEAR_4310,
        )
        for channel in (left_channel, right_channel)
    ]

