---
title: Teleoperate
subtitle: Leaders drive followers
section: Drive
order: 1
next_teaser: >-
  the arms track your hands. The next chapter is what to do when they don't.
---

Teleop reads each leader's servo positions, normalizes them against the
calibrated tick ranges, scales onto the YAM joint limits, and commands the
follower — at roughly 100 Hz.

Start with **one** pair:

```bash
uv run -m teleoperation --ports /dev/serial/by-id/<leader-id> --yam-arm-cans can0
```

Add the second only once direction and joint mapping are confirmed correct:

```bash
uv run -m teleoperation \
    --ports /dev/serial/by-id/<left-id> /dev/serial/by-id/<right-id> \
    --yam-arm-cans can0 can1
```

{% capture body %}
This commands physical hardware the moment it starts. Before you run it: confirm
the area is clear, an emergency stop is in reach, and the leader is already in a
pose that corresponds to a safe follower pose. There is no confirmation prompt
and no slow approach — the first command goes out immediately.
{% endcapture %}
{% include callout.html type="warn" title="Motion starts on launch" body=body %}

## Pairing is positional

The first leader in `--ports` drives the first channel in `--yam-arm-cans`. The
program pairs them with `zip`, so a longer list is silently truncated rather
than rejected — if one arm never moves in a two-arm run, check that both lists
have equal length and matching left-to-right order before anything else.

`--config-file` defaults to `outputs/mission_hacks_calibrations.json`.

## What gets commanded

Each cycle reads all six servos, maps them through
`load_bridge_config`, and sends the first six values to
`command_joint_pos`. Fixed joints are written at their configured constant on
every tick.

A servo read that fails or returns a tick outside `0..4095` raises immediately
and stops the process. That is deliberate: a bad read is a hardware fault, and
continuing to command an arm from corrupt data is worse than stopping.

## Stopping

Ctrl-C exits the loop and closes every leader bus and every arm, returning the
YAMs to a backdrivable state.

{% capture body %}
Stop immediately — don't try to correct in software — if a YAM joint moves
opposite its leader joint, the wrong joint moves, or the arm jumps at startup.
The first two are mapping errors covered in [Mapping](../mapping/); the third
means the leader pose didn't correspond to a safe follower pose, or the pairing
order is wrong.
{% endcapture %}
{% include callout.html type="info" title="What warrants an immediate stop" body=body %}
