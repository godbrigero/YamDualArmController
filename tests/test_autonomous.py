import unittest

import numpy as np

from autonomous.act_policy import ACTPolicy
from autonomous.control import bounded_action
from autonomous.policies import PolicyObservation, _validate_action


class AutonomousPolicyTests(unittest.TestCase):
    def test_observation_contract(self) -> None:
        image = np.zeros((240, 424, 3), dtype=np.uint8)
        PolicyObservation(
            state=np.zeros(14),
            images={"top": image, "left": image, "right": image},
            task="pick up the cup",
        ).validate()

    def test_observation_rejects_missing_camera(self) -> None:
        image = np.zeros((240, 424, 3), dtype=np.uint8)
        with self.assertRaisesRegex(ValueError, "right"):
            PolicyObservation(
                state=np.zeros(14), images={"top": image, "left": image}, task="task"
            ).validate()

    def test_action_contract(self) -> None:
        np.testing.assert_array_equal(_validate_action(list(range(14))), np.arange(14))
        with self.assertRaises(ValueError):
            _validate_action([0] * 13)

    def test_dataset_camera_aliases(self) -> None:
        self.assertEqual(ACTPolicy._role_for_feature("observation.images.top"), "top")
        self.assertEqual(ACTPolicy._role_for_feature("observation.images.wrist_1"), "left")
        self.assertEqual(ACTPolicy._role_for_feature("observation.images.wrist_2"), "right")

    def test_bounded_action_limits_each_step(self) -> None:
        target = np.full(14, 10.0)
        current = np.zeros(14)
        result = bounded_action(
            target,
            current,
            dt=0.1,
            max_joint_speed=0.5,
            max_gripper_speed=1.0,
        )
        expected = np.tile([0.05] * 6 + [0.1], 2)
        np.testing.assert_allclose(result, expected)


if __name__ == "__main__":
    unittest.main()
