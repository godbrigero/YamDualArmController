---
name: connect-yam-leader
description: Set up, calibrate, validate, run, and troubleshoot SO-101 Feetech leader arms mirroring i2rt YAM arms in projects initialized from YamDualArmController. Use for post-initializer setup, leader USB discovery, YAM CAN setup checks, calibration failures, bridge-config errors, servo ID mismatches, incorrect servo-to-YAM joint mappings or signs, reversed motion, wrong-joint motion, and starting single- or multi-arm teleoperation safely. Do not use for unrelated robots or generic motor-control development.
---

# Connect YAM Leader

Guide the user from an initialized project to verified YAM teleoperation. Base every command and diagnosis on the files currently present; do not assume ports or CAN channel names.

## Safety and operating rules

- Never start teleoperation automatically. It commands physical hardware immediately. Give the command and ask the user to confirm the area is clear, an emergency stop is reachable, and the leader pose corresponds to a safe follower pose.
- Start with one leader/YAM pair. Add the second pair only after direction and joint mapping are correct.
- Never hide an exception or suggest bypassing validation. Calibration and bridge errors intentionally terminate the process and preserve the previous JSON.
- Never change YAM joint ranges to correct reversed or wrong-joint motion. Correct the selected leader's `sign` or `yam_joint` instead.
- Never guess a new controller's mapping. Use `--template-leader` only when the user confirms the hardware layout is equivalent, then verify every joint.
- Treat servo pings and position reads as read-only, but treat calibration, JSON edits, CAN reconfiguration, and teleoperation as state-changing actions. Explain them before asking the user to run them.

## Workflow

### 1. Verify the initialized layout

Run read-only checks for these paths:

```text
scripts/calibrate.py
leader_yam_bridge/leader_yam_bridge.py
teleoperation/__main__.py
outputs/mission_hacks_calibrations.json
```

If one is missing, stop and report an incomplete initializer run. The current calibration implementation is the single `scripts/calibrate.py` file; do not expect a separate `scripts/calibration` package. Do not create an ad hoc replacement config. Re-run the current initializer or restore the missing managed files.

### 2. Inventory connected hardware

On the Linux host, inspect stable leader identities:

```bash
ls -l /dev/serial/by-id
```

Select aliases beginning with `usb-1a86_USB_Single_Serial_`. Prefer their full `/dev/serial/by-id/...` paths over transient `/dev/tty*` names.

Inspect each requested YAM CAN channel without changing it:

```bash
ip -details link show can0
ip -details link show can1
```

Use only the channels that exist and are configured for the intended YAM arms. If a channel is absent or down, explain the host-specific CAN setup needed; do not invent an interface name or run privileged changes without approval.

### 3. Inspect and health-check calibration

Show the seed/current configuration:

```bash
uv run scripts/calibrate.py --show
```

Health-check every discovered leader without modifying JSON:

```bash
uv run scripts/calibrate.py --check-only
```

For one controller, use a stable path:

```bash
uv run scripts/calibrate.py --check-only --port /dev/serial/by-id/<leader-id>
```

Interpret any failure using [references/troubleshooting.md](references/troubleshooting.md). Fix power, cabling, permissions, port identity, or servo IDs before calibration.

### 4. Calibrate

Calibrate all discovered controllers concurrently:

```bash
uv run scripts/calibrate.py
```

Or calibrate selected controllers by repeating `--port`:

```bash
uv run scripts/calibrate.py --port /dev/serial/by-id/<left-id> --port /dev/serial/by-id/<right-id>
```

Tell the user to press Enter when prompted, sweep every leader joint and gripper through both extremes, and press Ctrl-C only during the capture stage to finish. Calibration updates servo `output_range` values in memory, validates the entire generated bridge config, then atomically replaces `outputs/mission_hacks_calibrations.json`. Any earlier failure leaves the previous file unchanged.

If the controller is new, list available leader IDs with `--show`. Use `--template-leader <existing-full-id>` only after confirming which existing arm has the same servo layout and intended mapping.

### 5. Validate mapping before motion

Read [references/configuration.md](references/configuration.md) before editing or diagnosing IDs, signs, joint mappings, fixed joints, or ranges.

Confirm:

- the connected leader's full by-id basename is a key under `leader_arms`;
- every configured servo ID is physically present exactly once;
- `yam_joint` values are zero-based and cover every non-fixed YAM joint once;
- the fixed and servo-controlled YAM joints do not overlap;
- each `sign` is exactly `-1` or `1`;
- leader and YAM argument lists have equal lengths and are in matching left-to-right order.

Validate every leader entry through the real loader after any manual edit:

```bash
uv run python -c 'import json; from pathlib import Path; from leader_yam_bridge.leader_yam_bridge import load_bridge_config; p=Path("outputs/mission_hacks_calibrations.json"); ids=json.loads(p.read_text())["leader_arms"]; [load_bridge_config(p, leader_id) for leader_id in ids]; print("bridge config valid")'
```

### 6. Start teleoperation explicitly

For one verified pair:

```bash
uv run -m teleoperation --ports /dev/serial/by-id/<leader-id> --yam-arm-cans can0
```

For two verified pairs:

```bash
uv run -m teleoperation --ports /dev/serial/by-id/<left-id> /dev/serial/by-id/<right-id> --yam-arm-cans can0 can1
```

Pairing is positional: the first leader controls the first CAN arm. Require equal list lengths; the current program uses `zip`, so extra entries would otherwise be ignored. Keep the first movements small. Stop immediately if a YAM joint moves opposite the leader or the wrong YAM joint moves.

### 7. Diagnose observed motion

- Reversed correct joint: change only that servo's `sign` in that leader entry (`1` to `-1` or vice versa), validate, and retest one pair.
- Wrong YAM joint: correct that servo's zero-based `yam_joint`, preserving one-to-one coverage and the fixed joint, then validate and retest.
- Wrong servo reacts during a leader-joint test: identify the physical servo ID before editing; this is an ID/wiring/layout issue, not a range issue.
- Motion clips early or fails to reach the end: recalibrate `output_range`; do not alter `yam_arm.joint_ranges` unless the actual YAM model limits are wrong.
- Motion jumps, reads fail, or a servo intermittently disappears: stop teleoperation and resolve power/cabling/communication stability before continuing.

Lead troubleshooting responses with the next safe read-only command, quote the exact failing controller/servo, explain what the error means, and give one corrective action at a time.

## References

- Read [references/configuration.md](references/configuration.md) for the schema, canonical migrated mapping, and controlled mapping corrections.
- Read [references/troubleshooting.md](references/troubleshooting.md) for exact program errors, causes, and recovery actions.
