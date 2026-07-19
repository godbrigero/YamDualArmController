"""Local LeRobot ACT policy adapter."""

from __future__ import annotations

import numpy as np
import torch
from lerobot.policies.act.modeling_act import ACTPolicy as LeRobotACTPolicy
from lerobot.policies.factory import make_pre_post_processors

from autonomous.policies import AutonomousPolicy, PolicyObservation, _validate_action


class ACTPolicy(AutonomousPolicy):
    """Local LeRobot ACT checkpoint adapter (tested against LeRobot 0.6)."""

    _ROLE_ALIASES = {
        "top": "top",
        "left": "left",
        "right": "right",
        "wrist_1": "left",
        "wrist_2": "right",
    }

    def __init__(self, checkpoint: str, device: str | None = None) -> None:
        kwargs = {"device": device} if device else {}
        self._policy = LeRobotACTPolicy.from_pretrained(checkpoint, **kwargs)
        self._preprocessor, self._postprocessor = make_pre_post_processors(
            self._policy.config,
            pretrained_path=checkpoint,
        )
        image_features = list(self._policy.config.image_features)
        if len(image_features) != 3:
            raise ValueError(
                "this controller expects an ACT checkpoint with exactly three image features; "
                f"checkpoint declares {image_features}"
            )
        self._feature_roles = {
            feature: self._role_for_feature(feature) for feature in image_features
        }
        self.reset()

    @classmethod
    def _role_for_feature(cls, feature: str) -> str:
        suffix = feature.rsplit(".", 1)[-1]
        try:
            return cls._ROLE_ALIASES[suffix]
        except KeyError as exc:
            raise ValueError(
                f"cannot map ACT image feature {feature!r} to top/left/right; "
                "rename the checkpoint camera features or add an alias"
            ) from exc

    def reset(self) -> None:
        if hasattr(self, "_policy"):
            self._policy.reset()

    def predict(self, observation: PolicyObservation) -> np.ndarray:
        observation.validate()
        batch: dict[str, object] = {
            "observation.state": torch.from_numpy(
                np.asarray(observation.state, dtype=np.float32)
            ),
            "task": observation.task,
        }
        for feature, role in self._feature_roles.items():
            image = np.asarray(observation.images[role])
            batch[feature] = torch.from_numpy(image).permute(2, 0, 1).float() / 255.0

        processed = self._preprocessor(batch)
        with torch.inference_mode():
            action = self._policy.select_action(processed)
        action = self._postprocessor(action)
        if hasattr(action, "detach"):
            action = action.detach().cpu().numpy()
        return _validate_action(action)

