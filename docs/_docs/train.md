---
title: Train
subtitle: An ACT policy on your demos
section: Collect
order: 4
---

With the dataset converted, training is one LeRobot command:

```bash
HF_HUB_ENABLE_HF_TRANSFER=1 lerobot-train \
    --dataset.repo_id=<user>/<name> \
    --policy.type=act \
    --policy.device=cuda \
    --policy.push_to_hub=false \
    --batch_size=8 \
    --steps=50000 \
    --output_dir=outputs/act
```

Checkpoints land in `outputs/act`.

{% capture body %}
Falling training loss is necessary, not sufficient. ACT will fit fifty sloppy
demonstrations perfectly and still fail on the table. The honest signal is a
rollout on the real arms, not the curve.
{% endcapture %}
{% include callout.html type="warn" title="Loss is not success" body=body %}

## Keep the provenance

Record the dataset repo id alongside every run. A checkpoint whose training data
you can't identify isn't reproducible, and after a weekend of recording, two
datasets with similar names are indistinguishable from the checkpoint alone.

## Before the first rollout

The policy expects the observation distribution it was trained on. Camera
placement, lighting, and which channel is `can0` all have to match what you
recorded — the task didn't change, but the observations did.

Bring both arms to a known pose before the first inference step, keep the area
clear, and stay on the stop control. Everything in
[Teleoperate](../teleoperate/) about motion starting immediately applies with
more force here: the commands are coming from a model, not your hands.
