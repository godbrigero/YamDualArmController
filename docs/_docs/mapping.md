---
title: Mapping
subtitle: Which servo drives which joint
section: Set up
order: 5
next_teaser: >-
  the configuration is valid and verified. The next chapter puts it on the arms.
---

`outputs/mission_hacks_calibrations.json` is both the calibration output and the
runtime input. The top-level `yam_arm.joint_ranges` describes the follower's
physical limits and is shared by every leader. Each `leader_arms` entry — keyed
by the full by-id basename — owns its own port settings, servo ranges, joint
assignments, and signs.

## The schema

```json
{
  "yam_arm": { "joint_ranges": { "0": [-2.61799, 3.05433], "…": [] } },
  "leader_arms": {
    "usb-1a86_USB_Single_Serial_5AE6080681-if00": {
      "calibrated_at": "2026-07-18T16:54:35",
      "port": { "baud_rate": 1000000, "protocol_end": 0,
                "position_address": 56, "valid_position_range": [0, 4095] },
      "fixed_yam_joints": [ { "yam_joint": 4, "position": 0.0 } ],
      "servos": [ { "id": 1, "output_range": [838, 3441],
                    "yam_joint": 0, "sign": -1 } ]
    }
  }
}
```

| Field | Meaning |
|---|---|
| `output_range` | Raw ticks that **leader** servo emits, low to high |
| `yam_joint` | Zero-based index into the YAM joint vector it drives |
| `sign` | `1` direct, `-1` reversed |
| `fixed_yam_joints` | Joints held constant because no servo controls them |

Joint IDs are integers semantically even though JSON keys are strings, and the
loader requires them contiguous from `"0"` through `"N-1"`.

## The canonical mapping

The seed configuration carries the proven layout:

| Servo ID | YAM joint | Sign | Role |
|---:|---:|---:|---|
| 1 | 0 | −1 | pan / J1 |
| 2 | 1 | +1 | lift / J2 |
| 3 | 2 | −1 | elbow / J3 |
| 4 | 3 | −1 | wrist flex / J4 |
| 5 | 5 | −1 | wrist roll / J6 |
| 6 | 6 | +1 | gripper |

YAM joint 4 (J5) is fixed at `0.0`. Joint 6 is the gripper, with range
`[0.0, 1.0]` — normalized, not radians.

This is a known starting layout, not a guarantee. A newly built leader may have
different physical servo IDs or a different assembly order.

## Validate after any edit

Run every leader entry through the real loader — the same code path teleop uses:

```bash
uv run python -c 'import json; from pathlib import Path; from leader_yam_bridge.leader_yam_bridge import load_bridge_config; p=Path("outputs/mission_hacks_calibrations.json"); ids=json.loads(p.read_text())["leader_arms"]; [load_bridge_config(p, leader_id) for leader_id in ids]; print("bridge config valid")'
```

The validator enforces that servo IDs are unique and positive, every
`output_range` ascends, `sign` is exactly `-1` or `1`, no two servos target the
same joint, fixed positions fall inside their range, and every YAM joint is
either mapped or fixed. Any violation is fatal.

{% capture body %}
Never correct reversed or wrong-joint motion by editing `yam_arm.joint_ranges`.
Ranges control scaling and clipping, not identity. Direction lives in `sign`;
identity lives in `yam_joint`. And never reverse `[low, high]` to flip a
direction — the loader rejects descending ranges.
{% endcapture %}
{% include callout.html type="info" title="Fix the mapping, not the ranges" body=body %}

## Diagnosing motion

Change one variable at a time, on one leader/YAM pair, with small movements:

1. Correct joint, wrong direction → flip that servo's `sign`.
2. Wrong joint moves → correct that servo's `yam_joint`, keeping one-to-one
   coverage intact.
3. Moving a leader joint makes a *different servo ID* react → stop. That is a
   physical ID or wiring problem, and no config edit fixes it.
4. Motion clips before the end of travel → recalibrate `output_range`.

Recalibrate after any physical servo swap or ID change: the emitted tick range
belongs to that specific servo.
