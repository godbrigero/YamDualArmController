---
title: Convert
subtitle: Episodes to a LeRobot dataset
section: Collect
order: 2
next_teaser: >-
  the dataset is ACT-ready. The last chapter trains on it.
---

Conversion reads `episodes/<dataset>/`, decodes the videos, and builds a
`LeRobotDataset` with the features an ACT policy expects. Run it in the
environment that has LeRobot installed:

```bash
python convert_to_lerobot.py --src episodes/<dataset> --repo-id <user>/<name> [--push] [--private]
```

| Flag | Default |
|---|---|
| `--src` | `episodes/default` |
| `--repo-id` | required |
| `--fps` | `15` |
| `--task` | `bimanual teleoperation` |
| `--robot-type` | `yam_bimanual_so101_leader` |
| `--limit` | `0` (all episodes) |

Resolution is read from the first episode's `top.mp4`, so every episode in a
dataset must share one camera configuration.

## The feature schema

Three video streams — `observation.images.top`, `observation.images.wrist_1`,
`observation.images.wrist_2` — plus `observation.state` and `action`, each a
14-vector named `can0_j1 … can0_gripper, can1_j1 … can1_gripper`.

That naming is the contract between the recorder's column order and the trained
policy. If you change which channel is recorded first, this schema is what has
to change with it.

{% capture body %}
Use `--limit 2` for the first run on a new rig. It converts two episodes in
seconds and surfaces a resolution, missing-camera, or column-count mismatch
before you spend an hour on the full set.
{% endcapture %}
{% include callout.html type="info" title="Convert two before converting fifty" body=body %}

## Uploading

`--push` publishes as part of conversion. For an upload that has to survive a
bad connection, do it separately — `push_dataset.py` resumes an existing local
dataset:

```bash
HF_HUB_ENABLE_HF_TRANSFER=1 python push_dataset.py --repo-id <user>/<name> [--private] [--local <path>]
```

The local dataset lives under `~/.cache/huggingface/lerobot/<repo-id>`.

{% capture expect %}
`converting N episodes @ <W>x<H>, fps=15 -> <user>/<name>`, then per-episode
progress, and on success the dataset visible at
`huggingface.co/datasets/<user>/<name>`.
{% endcapture %}
{% include callout.html type="expect" label="You should see" body=expect %}
