---
title: Record
subtitle: Episodes from teleop
section: Collect
order: 1
next_teaser: >-
  episodes are on disk. The next chapter works out which of them are any good.
---

Recording captures what you drive: the follower's measured joint positions, the
leader's commanded targets, and one video per camera, sampled together at a
fixed rate.

{% capture body %}
The recording stack lives in `leader_yam_bridge/_v1/` and is the original
standalone pipeline. It has **not** been ported to the `leader_yam_bridge`
package that [Teleoperate](../teleoperate/) uses — it runs its own teleop loop
against its own `leader_calibration.json`, not `outputs/mission_hacks_calibrations.json`.
Treat the commands here as the legacy path until the port lands.
{% endcapture %}
{% include callout.html type="warn" title="This is the _v1 pipeline" body=body %}

## The control panel

`control_panel.py` is a one-page web UI on port **8080**. It discovers hardware,
launches the camera dashboard and the teleop processes, and proxies record
commands to the recorder:

```bash
.venv/bin/python control_panel.py
```

Open `http://localhost:8080`. Behind the buttons it spawns
`camera_dashboard.py` at 424×240 @ 15 fps and one `so101_teleop.py` per
configured pairing, and checks each CAN channel with `ip -br link show`.

The camera dashboard streams every RealSense camera into a Rerun web viewer on
port **9090** and hosts the recorder's control server on port **8090**:

```
POST /record/start   /record/stop   /record/save   /record/discard
POST /record/dataset?name=<name>
GET  /record/status
```

Anything the panel POSTs to `/api/record/…` is forwarded verbatim to 8090, so
you can drive a recording from `curl` if the UI is inconvenient.

## What an episode contains

```
episodes/<dataset>/episode_0007/
├── top.mp4
├── wrist_1.mp4
├── wrist_2.mp4
├── data.npz
└── meta.json
```

`data.npz` holds exactly three arrays: `state` and `action`, both
`float32` of shape `(N, 14)`, and `t`, `float64` of shape `(N,)` — wall-clock
timestamps. The 14 columns are `can0` first then `can1`, six joints and a
gripper each. `state` is the follower's measured position; `action` is the
leader's commanded target.

`meta.json` records `fps`, `n_frames`, `camera_frame_counts`, and the list of
cameras that produced video.

Episodes are written into a temporary directory and renamed into place on save,
so a discarded or crashed take never leaves a half-written `episode_XXXX`.

{% capture body %}
The recorder reads robot state from `/dev/shm/teleop_<channel>.json`, published
by the teleop process. A sample older than 0.5 seconds is treated as stale and
recorded as **zeros** for that arm. If teleop isn't running, you get an episode
full of zeros rather than an error — check that both arms report live state
before you record a full session.
{% endcapture %}
{% include callout.html type="info" title="Stale state records as zeros" body=body %}

## Naming the dataset

Set the dataset name before you start; episodes nest under
`episodes/<dataset>/` and the conversion step addresses them by that path.
Episode numbering continues from the highest existing index in that directory.
