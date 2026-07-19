---
title: Convert
subtitle: Episodes to a LeRobot dataset
section: Collect
order: 3
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
| `--format` | `act` (`molmoact2` renames the wrist streams for MolmoAct2 fine-tuning) |
| `--robot-type` | depends on `--format`: `yam_bimanual_so101_leader` / `bi_yam_follower` |
| `--limit` | `0` (all episodes) |
| `--curation` | `auto` (`require` / `off`) |
| `--curation-manifest` | `<src>/curation.json` |

Resolution is read from the first episode's `top.mp4`, so every episode in a
dataset must share one camera configuration.

## Only the episodes that survived triage

If [curation](/docs/curate/) has run over the source directory, conversion reads
its `curation.json` and skips everything it rejected, naming each one and why:

```text
curation (episodes/sweep/curation.json): kept 7 of 10 episodes
  query: pct_dropped < 40 AND worst_gap_ms < 500
  skipping episode_0007: capture_stall: a 1200 ms gap with no data recorded at all
```

The manifest is then copied into the dataset directory, so it is uploaded with
everything else and the Hub records which recordings the policy saw. Without a
manifest, `auto` converts everything and says so; `--curation require` refuses
to run at all, which is the setting to use in anything automated.

## The feature schema

Three video streams — `observation.images.top`, `observation.images.wrist_1`,
`observation.images.wrist_2` — plus `observation.state` and `action`, each a
14-vector named `can0_j1 … can0_gripper, can1_j1 … can1_gripper`.

That naming is the contract between the recorder's column order and the trained
policy. If you change which channel is recorded first, this schema is what has
to change with it.

With `--format molmoact2` the video streams become `observation.images.top`,
`observation.images.left`, `observation.images.right` (`wrist_2` → `left`,
`wrist_1` → `right`) and `robot_type` defaults to `bi_yam_follower` — the
schema the `yam_fold` fine-tuning mixture and the
`allenai/MolmoAct2-BimanualYAM` checkpoint expect. The state/action layout is
unchanged. This bakes in the rig's wiring: `wrist_1` films the right (`can1`)
arm and `wrist_2` the left (`can0`) arm. If a rig is ever cabled the other way,
fix the camera serial assignment at recording time rather than editing the key
mapping.

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
HF_HUB_ENABLE_HF_TRANSFER=1 python push_dataset.py --repo-id <user>/<name> \
    [--private] [--local <path>] [--require-curation]
```

It prints the curation manifest it found before uploading;
`--require-curation` turns a missing one from a warning into a refusal.

The local dataset lives under `~/.cache/huggingface/lerobot/<repo-id>`.

{% capture expect %}
`converting N episodes @ <W>x<H>, fps=15 -> <user>/<name>`, then per-episode
progress, and on success the dataset visible at
`huggingface.co/datasets/<user>/<name>`.
{% endcapture %}
{% include callout.html type="expect" label="You should see" body=expect %}
