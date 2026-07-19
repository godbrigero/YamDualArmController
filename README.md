# YAM ⟵ SO-101 Teleop + Camera Dashboard + ACT Pipeline

Bimanual teleoperation of **i2rt YAM** arms with **SO-101** leader arms, a live
**Rerun** camera dashboard, a one-click web **control panel**, and an
**episode-recording → LeRobot dataset → ACT training** pipeline.

Built for a hackathon on top of [`i2rt`](https://github.com/i2rt-robotics/i2rt)
(YAM arms, DM motors over CAN) and [LeRobot](https://github.com/huggingface/lerobot)
(ACT policy + dataset format).

## Documentation

**📖 [Full documentation →](https://godbrigero.github.io/YamDualArmController/)**

Set up, calibrate, verify the mapping, drive the arms, record, and train — every
error the code raises, with the fix. Source lives in [`docs/`](docs/).

### Fastest path: let the agent do it

```
/connect-yam-leader        # Claude Code
$connect-yam-leader        # Codex
```

The repository ships an agent skill ([`skills/connect-yam-leader/`](skills/connect-yam-leader/))
that runs the whole setup — hardware discovery, calibration, mapping validation,
and a safe first teleop — and diagnoses failures against the exact errors the
code raises. The initializer installs it into both `.claude/skills/` and
`.agents/skills/`, so it's available the moment setup finishes. It never starts
teleoperation on its own.

## Install

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/godbrigero/YamDualArmController/main/scripts/initialize_new_project.bash)"
```

Run it from inside the directory you want the project in — it installs into
`$PWD`. Requires [uv](https://docs.astral.sh/uv/getting-started/installation/).

## System

```
SO-101 leaders (Feetech STS3215, USB) ──► YAM followers (DM motors, CAN)
        │                                          │
        └── joint-space mapping (per-leader calibration by controller serial)
RealSense cameras (top + 2 wrists) ──► Rerun web dashboard
Control panel (:8080) ── one-click connect / teleop / record episodes
Episodes ──► LeRobotDataset ──► lerobot-train (ACT) ──► deploy
```

## Autonomous control

The autonomous runner uses the same observation/action layout as the `_v1`
dataset pipeline: left (`can0`) then right (`can1`), with six joints and one
gripper value per arm. Camera capture also matches the dataset defaults: RGB at
424x240 and 15 FPS. Pass camera serial numbers explicitly so their physical
roles cannot be accidentally reordered.

Run a trained LeRobot ACT checkpoint locally (omit `--execute` for a safe dry
run that prints actions):

```bash
python -m autonomous \
  --policy act --checkpoint outputs/act/checkpoints/last/pretrained_model \
  --task "put the cup in the bowl" \
  --left-arm-can can0 --right-arm-can can1 \
  --top TOP_SERIAL --left LEFT_SERIAL --right RIGHT_SERIAL \
  --execute
```

For MolmoAct2, Modal is the easiest deployment path. Install/configure the Modal
CLI, create a proxy token, then deploy the included endpoint. Modal prints the
prediction URL; use that exact URL as `--vla-url`.

```bash
# Development machine (once)
uvx --from modal modal setup
uvx --from modal modal workspace proxy-tokens create

# Deploy the public BimanualYAM checkpoint. Weights are cached in a Modal Volume.
uvx --from modal modal deploy autonomous/modal_vla.py

# Robot computer
export MODAL_PROXY_TOKEN_ID='wk-...'
export MODAL_PROXY_TOKEN_SECRET='ws-...'
python -m autonomous \
  --policy vla --vla-url 'https://YOUR-PREDICT-URL.modal.run' \
  --task "put the cup in the bowl" \
  --left-arm-can can0 --right-arm-can can1 \
  --top TOP_SERIAL --left LEFT_SERIAL --right RIGHT_SERIAL \
  --execute
```

If training saved a fine-tuned checkpoint in an existing Modal Volume, mount
that Volume and point the deployment at its directory (the path is relative to
the Volume but appears under `/models` in the inference container):

```bash
YAM_VLA_VOLUME='my-training-volume' \
YAM_VLA_MODEL='/models/checkpoints/my-yam-policy' \
uvx --from modal modal deploy autonomous/modal_vla.py
```

For a fine-tune pushed to Hugging Face, set `YAM_VLA_MODEL` to its repository
ID instead. To use a conventional GPU VM rather than Modal, run
`python -m autonomous.vla_server` and pass its full
`http://HOST:8000/predict` URL to the robot.

Keep a hand on the emergency stop and validate new checkpoints with dry runs.
The runner rejects malformed/non-finite actions, velocity-limits every command,
and returns both arms to gravity-comp idle on exit. MolmoAct2 expects the exact
camera order top, left, right and uses continuous actions with
`yam_dual_molmoact2` normalization.

## Components

| File | What it does |
|------|--------------|
| `control_panel.py` | One-page web control panel (`:8080`): auto-discovers leaders/YAMs/cameras, buttons for Connect / Start Teleop / Stop, episode recording (named datasets, start/stop/save/discard), embeds the Rerun camera view. |
| `so101_teleop.py` | SO-101 leader → YAM follower teleop. Absolute range-to-range joint mapping, slow-move-to-start, velocity clamp. Loads per-leader ranges from `leader_calibration.json` by controller serial. Publishes state to `/dev/shm` for the recorder. |
| `camera_dashboard.py` | Owns the RealSense cameras, streams them to a Rerun web dashboard (scene-top / wrists-bottom layout), and hosts the episode **recorder** (control server on `:8090`). |
| `scripts/calibrate.py` | Standalone concurrent multi-leader calibration command: health-checks every selected controller, captures all ranges together, then atomically updates `outputs/mission_hacks_calibrations.json`. |
| `check_leader.py` | Quick single-leader health check (USB detection, servo power/stability, motion-corruption test). |
| `check_cameras.py` | Snapshot each RealSense camera to verify it works / identify which is which. |
| `episode_writer.py` | Dependency-light episode format: one `mp4` per camera + `npz` of state/action/timestamps, under `episodes/<dataset>/episode_XXXX/`. |
| `convert_to_lerobot.py` | Convert `episodes/<dataset>/` → a `LeRobotDataset` (ACT-ready) and optionally push to the HF Hub. |
| `push_dataset.py` | Resumable HF upload of a local LeRobotDataset (uses `hf_transfer` for speed). |
| `outputs/mission_hacks_calibrations.json` | Zero-based YAM ranges plus per-controller servo IDs, output ranges, mappings, signs, and fixed joints used by the bridge API. |

## Requirements

- `i2rt` installed (YAM arm driver, CAN). See the i2rt repo.
- Python deps: `feetech-servo-sdk`, `pyrealsense2`, `opencv-python`, `rerun-sdk`, `numpy`.
- For dataset conversion / ACT training: `lerobot` (+ `accelerate`, `hf_transfer`) — typically a separate env.

## Quickstart

After installing, invoke `/connect-yam-leader` (Claude Code) or
`$connect-yam-leader` (Codex) for the guided setup and troubleshooting workflow,
or follow the steps below. Each one is a chapter in the
[documentation](https://godbrigero.github.io/YamDualArmController/).

```bash
# 1. Calibrate the leader arms (once per arm)
uv run scripts/calibrate.py

# 2. Start teleoperation — one pair first
uv run -m teleoperation --ports /dev/serial/by-id/<leader-id> --yam-arm-cans can0

# 3. Launch the control panel to record  →  open http://localhost:8080
python control_panel.py
#   - Connect (cameras) → Start Teleop → record episodes into named datasets

# 4. Convert recorded episodes to a LeRobot dataset (in the lerobot env)
python convert_to_lerobot.py --src episodes/<dataset> --repo-id <user>/<name> [--push]

# 5. Train ACT locally
HF_HUB_ENABLE_HF_TRANSFER=1 lerobot-train \
    --dataset.repo_id=<user>/<name> --policy.type=act --policy.device=cuda \
    --policy.push_to_hub=false --batch_size=8 --steps=50000 --output_dir=outputs/act
```

## Hardware notes

- Each SO-101 leader needs its **own** power supply (sharing one causes servo dropouts).
- RealSense cameras: on USB 2.0, use **color-only, low res** (e.g. 424×240@15); move to USB 3.0 for depth/higher res.
- YAM followers on `can0` / `can1` at 1 Mbit/s; leaders enumerate as `/dev/ttyACM*`.
