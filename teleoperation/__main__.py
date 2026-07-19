import time
import numpy as np
from argparse import ArgumentParser, Namespace

from i2rt.robots.get_robot import get_yam_robot
from i2rt.robots.utils import ArmType, GripperType

from leader_yam_bridge import get_mission_hacks_leader


def parse_args() -> Namespace:
    parser = ArgumentParser(description="Teleoperate the Mission Hacks leader")
    parser.add_argument(
        "--ports",
        type=str,
        default=["/dev/ttyUSB0"],
        nargs="+",
        help="The ports that represent the leaders. Usage: --ports /dev/ttyUSB0 /dev/ttyUSB1",
    )
    parser.add_argument(
        "--yam-arm-cans",
        type=str,
        default=["can0"],
        nargs="+",
        help="The CAN buses that the YAM arms are connected to. Usage: --yam-arm-cans can0 can1",
    )
    parser.add_argument(
        "--config-file",
        type=str,
        default="outputs/mission_hacks_calibrations.json",
        help="The config file to use for the leader. Usage: --config-file outputs/mission_hacks_calibrations.json",
    )
    return parser.parse_args()


namespace = parse_args()

leaders = [
    get_mission_hacks_leader(port, namespace.config_file) for port in namespace.ports
]

yam_arms = [
    get_yam_robot(
        channel=can_bus,
        arm_type=ArmType.YAM,
        gripper_type=GripperType.LINEAR_4310,
    )
    for can_bus in namespace.yam_arm_cans
]

leaders_to_yam_arms = dict(zip(leaders, yam_arms))

try:
    while True:
        for leader, yam_arm in leaders_to_yam_arms.items():
            leader_arm_q = leader.get_joint_pos()[:6]
            yam_arm.command_joint_pos(leader_arm_q)

        time.sleep(0.01)  # approximately 100 Hz

except KeyboardInterrupt:
    pass

finally:
    # Return both arms to their safely backdrivable state.
    for leader in leaders:
        leader.close()

    for yam_arm in yam_arms:
        yam_arm.close()
