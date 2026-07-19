---
title: Troubleshoot
subtitle: Exact errors and what they mean
section: Drive
order: 2
next_teaser: >-
  the arms are trustworthy. The remaining chapters turn driving into data.
---

{% capture body %}
`/connect-yam-leader` in Claude Code (or `$connect-yam-leader` in Codex) has
this whole table attached. Paste the error at it and it will name the failing
controller or servo and give you one corrective action at a time — see
[Guided setup](../guided-setup/).
{% endcapture %}
{% include callout.html type="info" title="Or let the skill diagnose it" body=body %}

Every error below is raised by name in the code. Lead with the read-only check,
change one thing, then re-verify.

## Discovery and identity

| Error | Cause | Fix |
|---|---|---|
| `Serial identity directory not found: /dev/serial/by-id` | Not on the hardware host, or USB never enumerated | Check the cable and that you're on the robot machine |
| `No usb-1a86_USB_Single_Serial_* controllers found` | No leader controller present | `ls -l /dev/serial/by-id` |
| `Unknown serial controller` / `Serial device not found` | Stale or wrong alias | Re-list by-id and use the exact current path |
| `No stable serial identity points to …` | A `/dev/tty*` path with no by-id alias | Use the by-id identity |
| `The same controller was selected more than once` | Two `--port` values resolve to one device | Drop the duplicate |
| `Bridge configuration not found: …` | Wrong working directory, or the seed config is missing | Check `pwd`; restore the seed rather than inventing ranges |

## Bus and servo

| Error | Cause | Fix |
|---|---|---|
| `Could not open <device>` | Disconnected, busy, or no permission | Close other processes; fix serial group membership — not by running as root |
| `Could not set baud rate to 1000000` | Wrong device or driver problem | Confirm it's the Feetech controller; keep the proven default |
| `Servo <id> communication failed (comm=…, error=…)` | Read failed on the bus | Check that leader's own supply and cable |
| `Servo <id> returned <raw>; expected 0..4095` | Corrupt read or wrong protocol/address | Inspect power and cabling; do not widen the valid range |
| `Health check failed: <leader-id>` | A servo missed pings | Read the per-servo counts and work from the pattern |

One servo failing while the rest pass is an ID, power, or wiring problem for
that servo. All servos failing is a bus-level power problem. Intermittent counts
are marginal power — most often a shared supply.

## Calibration

| Error | Meaning |
|---|---|
| `Servo <id> did not produce a stable initial reading` | Fewer than three of five reads agreed within tolerance — fix stability, don't widen tolerance |
| `Calibration for <leader-id> is incomplete (servo X: span Y)` | That joint moved less than `--minimum-span` ticks; sweep it fully and rerun |
| `New leader(s) require --template-leader` | Unknown controller; signs and joint mappings must be explicit |
| `Template leader is not configured` | The template string isn't an exact JSON key — copy it from `--show` |

Motion that clips early *after* a clean run means the sweep never reached both
extremes. Recalibrate.

## Configuration validation

| Error | Meaning |
|---|---|
| `YAM joint IDs must be contiguous from 0` | A missing, extra, or one-based key in `joint_ranges` |
| `YAM joint ranges must be finite and non-zero` | A zero-width or non-finite range |
| `Servo IDs must be unique and positive` | Duplicate IDs in one leader entry |
| `Servo <id> has an invalid output range` | Descending or equal bounds — recalibrate, don't reverse them |
| `Servo <id> has an invalid YAM mapping` | `sign` isn't ±1, or `yam_joint` is out of bounds |
| `Multiple servos map to one YAM joint` | Two servos target the same follower joint |
| `A YAM joint cannot be both mapped and fixed` | Remove the overlap; each joint has one owner |
| `Every YAM joint must be mapped or fixed` | A joint is uncovered |
| `Invalid leader config: …` | Shape, type, or conversion failure — the nested text names the value |

## CAN and teleop

| Symptom | Cause | Fix |
|---|---|---|
| CAN channel not found | Channel doesn't exist on this host | `ip -details link show`; configure the adapter |
| CAN channel is down | Exists but can't communicate | Bring it up at 1 Mbit/s, with approval |
| One arm never moves in a two-arm run | List lengths or order differ; `zip` ignores extras | Equal lengths, matching order |
| Correct joint moves backward | Wrong `sign` | Flip only that sign, validate, retest one pair |
| Wrong YAM joint moves | Wrong `yam_joint` | Correct it without creating gaps or duplicates |
| Arm moves unexpectedly at startup | Leader pose didn't match a safe follower pose, or pairing is wrong | Stop; realign; verify one pair |

{% capture body %}
Calibration and runtime errors are fatal on purpose. Do not add a
catch-and-continue loop around a failing leader read, skip one bad controller to
keep the others running, or save calibration after a partial failure. Each of
those turns a hardware fault into an arm moving on bad data.
{% endcapture %}
{% include callout.html type="warn" title="Don't swallow the failure" body=body %}
