"""Hardware-independent control-loop safety helpers."""

from __future__ import annotations

import math
from collections.abc import Iterator

import numpy as np

from autonomous.policies import ACTION_DIM


def bounded_action(
    target: np.ndarray,
    current: np.ndarray,
    *,
    dt: float,
    max_joint_speed: float,
    max_gripper_speed: float,
) -> np.ndarray:
    """Reject malformed targets and velocity-limit both 7-DoF arm commands."""
    target = np.asarray(target, dtype=np.float64)
    current = np.asarray(current, dtype=np.float64)
    if target.shape != (ACTION_DIM,) or current.shape != (ACTION_DIM,):
        raise ValueError(f"target and current must both have shape ({ACTION_DIM},)")
    if not np.isfinite(target).all() or not np.isfinite(current).all():
        raise ValueError("target and current must be finite")
    max_delta = np.tile(
        np.array([max_joint_speed] * 6 + [max_gripper_speed], dtype=np.float64), 2
    ) * dt
    return current + np.clip(target - current, -max_delta, max_delta)


def velocity_limited_ramp(
    start: np.ndarray,
    target: np.ndarray,
    *,
    dt: float,
    max_speed: float,
    minimum_duration: float = 0.0,
) -> Iterator[np.ndarray]:
    """Yield a linear move that honors both speed and minimum-time limits."""
    start = np.asarray(start, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if start.shape != (ACTION_DIM,) or target.shape != (ACTION_DIM,):
        raise ValueError(f"start and target must both have shape ({ACTION_DIM},)")
    if not np.isfinite(start).all() or not np.isfinite(target).all():
        raise ValueError("start and target must be finite")
    if dt <= 0 or max_speed <= 0 or minimum_duration < 0:
        raise ValueError(
            "dt and max_speed must be positive; minimum_duration cannot be negative"
        )

    largest_delta = float(np.max(np.abs(target - start)))
    steps = max(
        1,
        math.ceil(largest_delta / (max_speed * dt)),
        math.ceil(minimum_duration / dt),
    )
    for step in range(1, steps + 1):
        fraction = step / steps
        yield start * (1.0 - fraction) + target * fraction


def timed_ramp(
    start: np.ndarray,
    target: np.ndarray,
    *,
    dt: float,
    duration: float,
) -> Iterator[np.ndarray]:
    """Yield a linear move lasting approximately ``duration`` seconds."""
    if dt <= 0 or duration <= 0:
        raise ValueError("dt and duration must be positive")
    start = np.asarray(start, dtype=np.float64)
    target = np.asarray(target, dtype=np.float64)
    if start.shape != (ACTION_DIM,) or target.shape != (ACTION_DIM,):
        raise ValueError(f"start and target must both have shape ({ACTION_DIM},)")
    if not np.isfinite(start).all() or not np.isfinite(target).all():
        raise ValueError("start and target must be finite")

    steps = max(1, math.ceil(duration / dt))
    for step in range(1, steps + 1):
        fraction = step / steps
        yield start * (1.0 - fraction) + target * fraction
