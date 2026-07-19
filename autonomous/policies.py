"""Shared policy interface and ACT/MolmoAct2 implementations.

The robot process only depends on :class:`AutonomousPolicy`.  ACT inference is
local, while MolmoAct2 inference is sent to ``vla_server.py`` on a GPU host.
"""

from __future__ import annotations

import base64
import io
import json
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass
from typing import Mapping

import numpy as np
from PIL import Image


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


class MolmoAct2CloudPolicy(AutonomousPolicy):
    """HTTP client for a MolmoAct2 policy hosted by ``autonomous.vla_server``."""

    def __init__(
        self,
        endpoint: str,
        *,
        token: str | None = None,
        modal_key: str | None = None,
        modal_secret: str | None = None,
        timeout: float = 120.0,
        jpeg_quality: int = 90,
    ) -> None:
        self._url = endpoint.rstrip("/")
        self._token = token
        self._modal_key = modal_key
        self._modal_secret = modal_secret
        self._timeout = timeout
        self._jpeg_quality = jpeg_quality
        self._actions: deque[np.ndarray] = deque()

    def reset(self) -> None:
        self._actions.clear()

    def _encode_image(self, image: np.ndarray) -> str:
        buffer = io.BytesIO()
        Image.fromarray(image, mode="RGB").save(
            buffer, format="JPEG", quality=self._jpeg_quality
        )
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    def predict(self, observation: PolicyObservation) -> np.ndarray:
        observation.validate()
        if self._actions:
            return self._actions.popleft()

        payload = json.dumps(
            {
                "task": observation.task,
                "state": np.asarray(observation.state, dtype=np.float32).tolist(),
                "images": {
                    role: self._encode_image(np.asarray(observation.images[role]))
                    for role in CAMERA_ROLES
                },
            }
        ).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        if self._modal_key:
            headers["Modal-Key"] = self._modal_key
        if self._modal_secret:
            headers["Modal-Secret"] = self._modal_secret
        request = urllib.request.Request(self._url, data=payload, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self._timeout) as response:
                result = json.load(response)
        except urllib.error.HTTPError as exc:
            detail = exc.read(2048).decode("utf-8", errors="replace")
            raise RuntimeError(f"VLA server returned HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"could not reach VLA server at {self._url}: {exc.reason}") from exc

        raw_actions = result.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise RuntimeError("VLA server response did not contain a non-empty 'actions' list")
        self._actions.extend(_validate_action(action) for action in raw_actions)
        return self._actions.popleft()
