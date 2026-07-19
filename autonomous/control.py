"""Hardware-independent control-loop safety helpers."""

from __future__ import annotations

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

