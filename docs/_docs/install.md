---
title: Install
subtitle: uv, dependencies, managed files
section: Set up
order: 2
next_teaser: >-
  the project is on disk. The next chapter finds the hardware attached to it.
---

{% capture body %}
[Guided setup](../guided-setup/) runs everything on this page and the three
that follow — invoke `/connect-yam-leader` in Claude Code or
`$connect-yam-leader` in Codex and it drives the whole path, diagnosing
failures as they happen.
{% endcapture %}
{% include callout.html type="info" title="There is an agent skill for all of this" body=body %}

The initializer clones this repository into a temporary directory, copies the
managed teleop code into your project, sets up a uv environment, and deletes the
clone. Run it from inside the directory you want the project in — it installs
into `$PWD`, not into a directory you name.

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/godbrigero/YamDualArmController/main/scripts/initialize_new_project.bash)"
```

uv is a hard prerequisite. Without it the script aborts before touching
anything, with a pointer to the install instructions.

## What lands in your project

| Path | Behavior on re-run |
|---|---|
| `scripts/calibrate.py` | Overwritten |
| `leader_yam_bridge/` | Overwritten |
| `teleoperation/` | Overwritten |
| `.claude/skills/connect-yam-leader/` and `.agents/skills/…` | Overwritten |
| `outputs/mission_hacks_calibrations.json` | **Preserved** if it already exists |

{% capture body %}
Re-running the initializer deletes and re-copies the managed directories
wholesale. Local edits under `leader_yam_bridge/`, `teleoperation/`, or the
skill directories are lost. Only your calibration file is treated as yours.
{% endcapture %}
{% include callout.html type="warn" title="Managed directories are replaced, not merged" body=body %}

## The environment

The project targets Python 3.12 exactly (`>=3.12,<3.13`) and is not built as a
package — you run modules out of the repo with `uv run`.

The initializer's `uv add` step installs `numpy`, `feetech-servo-sdk`, and
`i2rt` from git. The full `pyproject.toml` also declares `lerobot[dataset,training]`,
`rerun-sdk`, `pyrealsense2`, `opencv-python-headless`, `accelerate`,
`hf-transfer`, and `huggingface-hub` — the dependencies the recording and
training pipeline needs. If you only teleoperate, the three the initializer adds
are enough.

{% capture expect %}
Per-file `Installing:` / `Updating:` / `Already up to date:` lines, then
`Configuring UV project dependencies...`, then `Project initialization complete.`
{% endcapture %}
{% include callout.html type="expect" label="You should see" body=expect %}
