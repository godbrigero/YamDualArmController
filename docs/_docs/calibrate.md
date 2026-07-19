---
title: Calibrate
subtitle: Capture each leader's tick range
section: Set up
order: 4
next_teaser: >-
  every servo has a measured range. The next chapter checks it points at the
  right joint.
---

Calibration records the raw tick range each leader servo emits across its full
travel, so normalized leader motion can be scaled onto the YAM's joint limits.
It changes two things and nothing else: each servo's `output_range`, and that
leader's `calibrated_at` timestamp.

## Look before you change

Show the current configuration — YAM ranges, every leader, every servo mapping:

```bash
uv run scripts/calibrate.py --show
```

Health-check every discovered leader without writing anything:

```bash
uv run scripts/calibrate.py --check-only
```

The health check pings each configured servo 15 times (`--pings`) and requires
every ping to land. One servo at `0/15` while the others pass means that ID is
absent, duplicated, unpowered, or disconnected. Every servo at `0/15` means the
bus is unpowered — check the brick before you touch any IDs.

{% capture expect %}
A per-servo line for each controller, then
`[health] All controllers and servos are stable.`
{% endcapture %}
{% include callout.html type="expect" label="You should see" body=expect %}

## Calibrate

With no `--port`, every connected `usb-1a86_USB_Single_Serial_*` controller is
selected and calibrated concurrently:

```bash
uv run scripts/calibrate.py
```

To select specific controllers, repeat `--port`:

```bash
uv run scripts/calibrate.py \
    --port /dev/serial/by-id/<left-id> \
    --port /dev/serial/by-id/<right-id>
```

The run takes stable initial readings, waits on **Enter**, then streams a live
min/max/span table per servo. Sweep every joint and the gripper on every leader
through both mechanical extremes, then press **Ctrl-C** to finish.

{% capture body %}
Ctrl-C is the intended way to end the capture stage — but only that stage. Press
it before the sweep starts and you abort the run. Every servo must reach a span
of at least 50 ticks (`--minimum-span`) or the run fails with
`Calibration for <leader-id> is incomplete`.
{% endcapture %}
{% include callout.html type="info" title="Ctrl-C ends the sweep, not the script" body=body %}

## The write is transactional

Nothing is saved until every selected controller succeeds. The calibrator holds
all results in memory, writes a temporary sibling file, re-validates every
leader entry through the real runtime loader, and only then does one atomic
replacement of `outputs/mission_hacks_calibrations.json`.

If the run fails at any point, the previous file is untouched — deliberately.
There are no partial results to recover.

## A leader with no entry

A newly built controller has no mapping, and calibration will not invent signs
and joint assignments for it:

```
New leader(s) require --template-leader so servo signs and YAM mappings are explicit
```

Copy an existing leader's layout only after confirming the hardware is
equivalent, then verify every joint before trusting it:

```bash
uv run scripts/calibrate.py --template-leader usb-1a86_USB_Single_Serial_<existing>-if00
```
