# Bridge configuration and mapping

## Contents

- Configuration ownership
- Field meanings
- Canonical migrated mapping
- Diagnosing mapping problems
- Controlled edits

## Configuration ownership

`outputs/mission_hacks_calibrations.json` is both the calibration output and the runtime bridge input. The top-level `yam_arm.joint_ranges` map describes YAM target ranges shared by all leaders. Each `leader_arms` entry is keyed by the controller's full `/dev/serial/by-id` basename and owns its port settings, servo calibration, mapping, signs, and fixed joints.

JSON map keys are strings, but YAM joint IDs are integers semantically and are zero-based. The loader requires joint-range keys to be contiguous from `"0"` through `"N-1"`.

Calibration changes only:

- each selected servo's `output_range`;
- the selected leader's `calibrated_at` timestamp.

Calibration must preserve YAM ranges, servo IDs, `yam_joint`, `sign`, port settings, and fixed joints. It saves only after every selected controller succeeds and every leader entry validates.

## Field meanings

| Field | Meaning | Correction rule |
|---|---|---|
| `yam_arm.joint_ranges` | Physical target range of each YAM joint | Do not change for leader direction or calibration problems |
| `leader_arms.<id>` | Configuration for one physical leader controller | Keep mappings per leader; they may differ |
| `servos[].id` | Numeric Feetech ID addressed on that leader bus | Must match the physical servo ID and be unique |
| `servos[].output_range` | Minimum and maximum raw ticks emitted by that leader servo | Recreate by calibration; low must be less than high |
| `servos[].yam_joint` | Zero-based target index in the YAM joint vector | Change only when the wrong YAM joint is controlled |
| `servos[].sign` | Whether normalized leader motion is direct (`1`) or reversed (`-1`) | Flip when the correct joint moves in the wrong direction |
| `fixed_yam_joints` | YAM joints held at a constant position because no servo controls them | Must not overlap a servo-controlled joint |
| `port` | Feetech SDK bus parameters | Defaults are 1,000,000 baud, protocol end `0`, address `56`, ticks `0..4095` |

`output_range` belongs to the leader servo even though it is named an output: the servo outputs raw position ticks. `yam_arm.joint_ranges` belongs to the follower target.

## Canonical migrated mapping

The proven `_v1` mapping represented by the seed configuration is:

| Feetech servo ID | YAM joint | Sign | Role |
|---:|---:|---:|---|
| 1 | 0 | -1 | pan / J1 |
| 2 | 1 | +1 | lift / J2 |
| 3 | 2 | -1 | elbow / J3 |
| 4 | 3 | -1 | wrist flex / J4 |
| 5 | 5 | -1 | wrist roll / J6 |
| 6 | 6 | +1 | gripper |

YAM joint `4` (J5) is fixed at `0.0`. These values are a known starting layout, not permission to assume every newly built leader has identical signs or IDs.

## Diagnosing mapping problems

Change one variable at a time while testing one leader/YAM pair:

1. Put the leader and YAM in safe, corresponding poses.
2. Move only one leader joint by a small amount.
3. Observe which YAM joint moves and in which direction.
4. If the correct YAM joint moves backward, flip only `sign`.
5. If a different YAM joint moves, correct only `yam_joint` while retaining complete one-to-one coverage.
6. If moving the expected physical leader joint changes a different servo ID, stop and resolve the physical ID/layout mismatch first.
7. Validate the whole JSON before retesting.

Do not compensate for an ID or mapping error by swapping calibration ranges. A range controls scaling and clipping, not identity. Do not compensate for a sign error by reversing `[low, high]`; the loader rejects zero or descending widths and direction is represented explicitly by `sign`.

## Servo ID mismatch procedure

A configured ID that receives fewer pings than the others may be unpowered, disconnected, duplicated, or programmed with a different ID.

1. Stop teleoperation and work with one leader bus.
2. Confirm that leader's full by-id identity and power supply.
3. Run `uv run scripts/calibrate.py --check-only --port /dev/serial/by-id/<leader-id>`.
4. Note exactly which configured IDs fail. If all fail, diagnose bus power/port/protocol before IDs.
5. Check physical build records or use the approved Feetech ID inspection/configuration tool. Do not broadcast an ID-write command and do not change IDs while multiple servos are connected unless the hardware procedure explicitly supports it.
6. If the physical IDs are intentional, update only `servos[].id` for that leader, maintain uniqueness, validate, then rerun the health check.
7. Recalibrate after any physical ID or servo replacement because the emitted tick range belongs to that servo.

## Controlled edits

Before changing a leader mapping, identify its exact full key and edit only that entry. Do not apply a sign learned on one controller to every controller.

After editing, run the real loader for every leader:

```bash
uv run python -c 'import json; from pathlib import Path; from leader_yam_bridge.leader_yam_bridge import load_bridge_config; p=Path("outputs/mission_hacks_calibrations.json"); ids=json.loads(p.read_text())["leader_arms"]; [load_bridge_config(p, leader_id) for leader_id in ids]; print("bridge config valid")'
```

Then rerun the selected leader's check-only command. Test teleoperation with one pair and small movements before adding other arms.
