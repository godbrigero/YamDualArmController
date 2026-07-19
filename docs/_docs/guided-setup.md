---
title: Guided setup
subtitle: Let the agent walk you through it
section: Set up
order: 1
read_time: false
next_teaser: >-
  the agent knows the path. The rest of these chapters are the same path,
  written out.
---

**This is the fastest way through everything on this site.** The repository
ships an agent skill that runs the entire setup — hardware discovery,
calibration, mapping validation, and a safe first teleop — and diagnoses
failures against the exact errors the code raises.

Invoke it in whichever agent you use:

```text
/connect-yam-leader
```

```text
$connect-yam-leader
```

The first is Claude Code, the second is Codex. Nothing else to install: the
initializer copies the skill into both `.claude/skills/` and `.agents/skills/`
in your project.

{% capture body %}
Type the invocation and describe where you're stuck — "my left leader fails the
health check", "the elbow moves backward", "which port is which". The skill
leads with the next safe **read-only** command, quotes the exact failing
controller or servo, and gives you one corrective action at a time.
{% endcapture %}
{% include callout.html type="info" title="It's also the fastest way out of a failure" body=body %}

## What it will and won't do

It will inventory your leaders and CAN channels, run health checks, walk the
calibration sweep, validate the bridge config through the real loader, and
diagnose reversed or wrong-joint motion.

It will **not** start teleoperation on its own. Motion commands physical
hardware immediately, so the skill always hands you the command and asks you to
confirm the area is clear, an e-stop is in reach, and the leader pose
corresponds to a safe follower pose.

It also won't hide an exception, skip a failed controller to keep the others
running, or suggest bypassing validation — the failures in this system are fatal
on purpose.

## When you'd read the chapters instead

The remaining chapters are the same path in prose: useful when you want to
understand the config schema before editing it, look up an error by name, or
work without an agent in the loop. Start with [Install](../install/).
