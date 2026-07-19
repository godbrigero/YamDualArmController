from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INITIALIZER = ROOT / "scripts" / "initialize_new_project.bash"
SKILL = ROOT / "skills" / "connect-yam-leader"
CONFIG = ROOT / "outputs" / "mission_hacks_calibrations.json"
WINNOW = ROOT / "third_party" / "winnow"


class InitializeNewProjectTest(unittest.TestCase):
    def initialize(self, target: Path) -> None:
        # clone winnow from the submodule already on disk rather than from GitHub,
        # so the test neither needs the network nor depends on winnow's main branch
        environment = dict(os.environ, YAM_INITIALIZER_WINNOW_URL=str(WINNOW))
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
            env=environment,
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
            self.assertTrue((target / "curation/__main__.py").is_file())
            self.assertTrue((target / "third_party/winnow/winnow/catalog.py").is_file())
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

    def add_ruckig_build_constraint(self, target: Path) -> None:
        subprocess.run(
            [
                "bash",
                "-c",
                'source "$1"; ensure_ruckig_build_constraint "$2"',
                "initializer-test",
                str(INITIALIZER),
                str(target),
            ],
            check=True,
            cwd=ROOT,
            capture_output=True,
            text=True,
        )

    def test_adds_ruckig_build_constraint_to_new_uv_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            pyproject = target / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "example"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )

            self.add_ruckig_build_constraint(target)

            self.assertIn(
                '[tool.uv]\nbuild-constraint-dependencies = '
                '["scikit-build-core<0.10"]',
                pyproject.read_text(encoding="utf-8"),
            )

    def test_adds_ruckig_constraint_to_existing_uv_table_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            pyproject = target / "pyproject.toml"
            pyproject.write_text(
                '[project]\nname = "example"\nversion = "0.1.0"\n\n'
                '[tool.uv]\npackage = false\n',
                encoding="utf-8",
            )

            self.add_ruckig_build_constraint(target)
            self.add_ruckig_build_constraint(target)

            contents = pyproject.read_text(encoding="utf-8")
            self.assertEqual(contents.count("build-constraint-dependencies"), 1)
            self.assertIn("package = false", contents)

    def test_uv_add_receives_the_ruckig_build_constraint_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "project"
            scratch = Path(directory) / "scratch"
            target.mkdir()
            scratch.mkdir()
            (target / "pyproject.toml").write_text(
                '[project]\nname = "example"\nversion = "0.1.0"\n',
                encoding="utf-8",
            )

            uv_log = Path(directory) / "uv.log"
            fake_uv = Path(directory) / "uv"
            fake_uv.write_text(
                "#!/usr/bin/env bash\n"
                "printf '%s\\n' \"$UV_BUILD_CONSTRAINT\" >\"$YAM_TEST_UV_LOG\"\n"
                "sed -n '1p' \"$UV_BUILD_CONSTRAINT\" >>\"$YAM_TEST_UV_LOG\"\n",
                encoding="utf-8",
            )
            fake_uv.chmod(0o755)

            subprocess.run(
                [
                    "bash",
                    "-c",
                    'source "$1"; uv_executable="$2"; temporary_directory="$3"; '
                    'export YAM_TEST_UV_LOG="$4"; configure_uv_project "$5"',
                    "initializer-test",
                    str(INITIALIZER),
                    str(fake_uv),
                    str(scratch),
                    str(uv_log),
                    str(target),
                ],
                check=True,
                cwd=ROOT,
                capture_output=True,
                text=True,
            )

            constraint_log = uv_log.read_text(encoding="utf-8").splitlines()
            constraint_path = Path(constraint_log[0])
            self.assertEqual(constraint_path.parent, scratch)
            self.assertEqual(constraint_log[1], "scikit-build-core<0.10")


if __name__ == "__main__":
    unittest.main()
