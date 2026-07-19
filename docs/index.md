---
layout: home
title: Home
headline: Two Arms, One
headline_accent: Operator
lede: >-
  Bimanual teleoperation of i2rt YAM arms with SO-101 leaders — calibrated by
  serial, validated before motion, and recorded into datasets you can train on.
agent_prompt:
  title: Let your AI editor set it up
  subtitle: >-
    Copy this into a chat opened in the folder you want the project in. It
    installs, finds your hardware, calibrates, and stops before anything moves.
  targets:
    - Claude Code
    - Codex
    - Cursor
  body: |
    Set me up for bimanual YAM teleoperation — two i2rt YAM arms driven by SO-101 leader arms. I am on the Linux host the arms are plugged into. Run these in order, in the current directory:

    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/godbrigero/YamDualArmController/main/scripts/initialize_new_project.bash)"   # needs uv installed first
    ls -l /dev/serial/by-id   # every SO-101 leader should appear here
    uv run scripts/calibrate.py --show
    uv run scripts/calibrate.py --check-only

    Then use the skill the installer wrote into .claude/skills/ and .agents/skills/: invoke /connect-yam-leader in Claude Code or $connect-yam-leader in Codex, and follow it to calibrate each leader and validate its joint mapping.

    Finish line: --check-only passes for every leader in /dev/serial/by-id, outputs/mission_hacks_calibrations.json has an entry for each one, and load_bridge_config accepts every entry.

    Do not start teleoperation — it commands real arms the moment it runs. Stop at the finish line and print the exact teleop command for me to run myself. Do not browse documentation before the finish line passes; if a step fails, fetch https://godbrigero.github.io/YamDualArmController/docs/troubleshoot/ and match the exact error.
quickstart:
  lead: Rather drive it yourself?
  steps:
    - label: Install into the current directory
      command: /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/godbrigero/YamDualArmController/main/scripts/initialize_new_project.bash)"
      note: uv is the only prerequisite. Your calibration file is never overwritten.
    - label: Run the skill that ships with it
      sigil: ">_"
      command: /connect-yam-leader
      note: In Claude Code. Codex users invoke $connect-yam-leader. It handles discovery, calibration, and mapping checks, and never starts teleop on its own.
actions:
  - title: Guided setup
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

## The same YAM startup, in one command

With native YAM leader hardware, manual control normally means starting two
workers — one for the follower and one for the leader — in separate terminals:

```bash
# Terminal 1: YAM follower
python examples/minimum_gello/minimum_gello.py \
  --gripper linear_4310 --mode follower --can-channel can0 --bilateral-kp 0.2

# Terminal 2: native YAM leader
python examples/minimum_gello/minimum_gello.py \
  --gripper yam_teaching_handle --mode leader --can-channel can1 --bilateral-kp 0.2
```

This controller does the same leader-to-follower job with one worker:

```bash
uv run -m teleoperation \
  --ports /dev/serial/by-id/<leader-id> \
  --yam-arm-cans can0
```

`--yam-arm-cans can0` is still the normal YAM follower connection. The only
change is that `--ports` opens the SO-101 leader over USB in the same process,
instead of starting a second worker for a native YAM leader on CAN. For two
arms, pass two leader ports and two CAN channels to that same command. See
[Teleoperate]({{ '/docs/teleoperate/' | relative_url }}) for the bimanual form
and safety notes.

## What the skill actually does

The prompt above hands the whole path to your agent: hardware discovery,
calibration, mapping validation, and a diagnosis for every error the code can
raise. It is the same [`/connect-yam-leader`](/docs/guided-setup/) skill that
lands in `.claude/skills/` and `.agents/skills/` when you install — so you can
re-invoke it any time a leader misbehaves, not just on day one. It will not
start teleoperation for you; that stays a decision you make with a hand on the
e-stop.

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
