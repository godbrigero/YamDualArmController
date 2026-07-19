from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INITIALIZER = ROOT / "scripts" / "initialize_new_project.bash"
SKILL = ROOT / "skills" / "connect-yam-leader"
CONFIG = ROOT / "outputs" / "mission_hacks_calibrations.json"


class InitializeNewProjectTest(unittest.TestCase):
    def initialize(self, target: Path) -> None:
        subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; run_project_initialization "$2" "$3"',
                "initializer-test",
                str(INITIALIZER),
                str(ROOT),
                str(target),
            ],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_installs_runtime_config_and_both_agent_skills(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.initialize(target)

            self.assertTrue((target / "scripts/calibrate.py").is_file())
            self.assertTrue((target / "leader_yam_bridge/leader_yam_bridge.py").is_file())
            self.assertTrue((target / "teleoperation/__main__.py").is_file())
            self.assertEqual(
                (target / "outputs/mission_hacks_calibrations.json").read_bytes(),
                CONFIG.read_bytes(),
            )

            for agent_directory in (".agents", ".claude"):
                installed = (
                    target
                    / agent_directory
                    / "skills/connect-yam-leader/SKILL.md"
                )
                self.assertEqual(installed.read_bytes(), (SKILL / "SKILL.md").read_bytes())
                self.assertTrue(
                    (installed.parent / "references/configuration.md").is_file()
                )
                self.assertTrue(
                    (installed.parent / "references/troubleshooting.md").is_file()
                )

    def test_rerun_preserves_user_calibration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            self.initialize(target)
            target_config = target / "outputs/mission_hacks_calibrations.json"
            user_calibration = b'{"user": "calibration must survive"}\n'
            target_config.write_bytes(user_calibration)

            self.initialize(target)

            self.assertEqual(target_config.read_bytes(), user_calibration)


if __name__ == "__main__":
    unittest.main()
