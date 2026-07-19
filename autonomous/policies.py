"""Shared contracts for autonomous ACT inference."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Mapping

import numpy as np


ACTION_DIM = 14
CAMERA_ROLES = ("top", "left", "right")


@dataclass(frozen=True)
class PolicyObservation:
    """One bimanual observation in raw robot units and RGB camera pixels."""

    state: np.ndarray
    images: Mapping[str, np.ndarray]
    task: str

    def validate(self) -> None:
        state = np.asarray(self.state)
        if state.shape != (ACTION_DIM,) or not np.isfinite(state).all():
            raise ValueError(f"state must be {ACTION_DIM} finite values; got {state.shape}")
        for role in CAMERA_ROLES:
            if role not in self.images:
                raise ValueError(f"missing {role!r} camera image")
            image = np.asarray(self.images[role])
            if image.ndim != 3 or image.shape[2] != 3 or image.dtype != np.uint8:
                raise ValueError(
                    f"{role!r} image must be HxWx3 uint8 RGB; got {image.shape} {image.dtype}"
                )
        if not self.task.strip():
            raise ValueError("task instruction must not be empty")


class AutonomousPolicy(ABC):
    """Common contract used by the YAM control loop."""

    @abstractmethod
    def predict(self, observation: PolicyObservation) -> np.ndarray:
        """Return one absolute target: left arm then right arm, 7 values each."""

    def reset(self) -> None:
        """Reset action-chunk state at the start of a run."""

    def close(self) -> None:
        """Release optional policy resources."""


def _validate_action(action: object) -> np.ndarray:
    value = np.asarray(action, dtype=np.float32).reshape(-1)
    if value.shape != (ACTION_DIM,):
        raise ValueError(f"policy action must contain {ACTION_DIM} values; got {value.shape}")
    if not np.isfinite(value).all():
        raise ValueError("policy returned a non-finite action")
    return value
