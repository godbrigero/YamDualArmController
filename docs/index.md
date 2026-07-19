---
layout: home
title: Home
headline: Two Arms, One
headline_accent: Operator
lede: >-
  Bimanual teleoperation of i2rt YAM arms with SO-101 leaders — calibrated by
  serial, validated before motion, and recorded into datasets you can train on.
actions:
  - title: Run /connect-yam-leader
    url: /docs/guided-setup/
    glyph: ">_"
    accent: true
  - title: Install
    url: /docs/install/
  - title: Repository
    url: https://github.com/godbrigero/YamDualArmController
    external: true
show_announcements: false
---

## Start here: the agent does the setup

This repository ships an agent skill that runs the whole path — hardware
discovery, calibration, mapping validation, and a safe first teleop — and
diagnoses failures against the exact errors the code raises. Invoke it:

```text
/connect-yam-leader        # Claude Code
$connect-yam-leader        # Codex
```

It is already in your project after [Install](/docs/install/), in both
`.claude/skills/` and `.agents/skills/`. See [Guided setup](/docs/guided-setup/)
for what it will and won't do — notably, it never starts teleoperation on its
own.

## The path

Install the project, identify every leader and CAN channel, calibrate each
leader's tick range, verify the mapping points at the right joints in the right
direction, and only then drive the arms. Recording and training build on top of
a rig you already trust.

## Two buses, one config

`outputs/mission_hacks_calibrations.json` is the single source of truth. It is
what calibration writes, what teleop reads, and what the validator checks. Every
leader is keyed by its stable `/dev/serial/by-id` name, so a leader keeps its
calibration no matter which USB port it lands on.

## Failures are fatal on purpose

Calibration is transactional — nothing is saved unless every controller
succeeds. A corrupt servo read stops teleoperation rather than commanding an arm
from bad data. The [Troubleshoot](/docs/troubleshoot/) chapter lists every error
by name, what causes it, and the one change that fixes it.
