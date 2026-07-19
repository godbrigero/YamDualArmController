---
title: Curate
subtitle: Which episodes are worth training on
section: Collect
order: 2
next_teaser: >-
  the corpus has been triaged. The next chapter converts the survivors.
---

Not every recording is worth training on. An operator fumbles a grasp, a camera
drops a second of footage, an episode gets cut short. Train on all of it and the
policy learns the mistakes along with the demonstrations — and nothing in a
`LeRobotDataset` tells you afterwards which recordings were the problem.

Curation answers that question before conversion, and writes the answer down.

```bash
uv run -m curation --src episodes/<dataset>
```

That produces `episodes/<dataset>/curation.json`: the episodes that survived,
the ones that did not, and a sentence explaining every rejection. Conversion
reads it automatically, so the rejects never reach the Hub.

## What is doing the measuring

The measurements come from [winnow](https://github.com/AdamEXu/winnow), which
ships as a submodule in `third_party/winnow`. It ingests each `episode_XXXX/`
into a [Rerun](https://rerun.io) recording, serves the whole corpus as a
catalog, and reduces it to one row per episode in SQL. The episode layout it
expects — three `mp4`s plus `data.npz` and `meta.json` — is exactly what the
[recorder](/docs/record/) writes, so nothing has to be converted first.

Winnow pins `rerun-sdk==0.34.1` and `datafusion~=53.0`, which this project does
not, so every stage runs as a subprocess in the submodule's own uv environment.
Nothing about it enters the teleop environment.

```bash
git submodule update --init third_party/winnow   # once, if you cloned without it
```

Derived artifacts land in `episodes/<dataset>/.winnow/` — the `.rrd` recordings,
the per-frame video signals, the feature table, the detector firings. Each stage
is skipped if its artifact already exists; `--refresh` forces the work again.

## Two filters, and neither is a score

An episode is kept when it passes both.

**A predicate over the metrics.** The catalog's SQL reduction gives every episode
a row — `n_frames`, `duration_s`, `true_hz`, `pct_dropped`, `worst_gap_ms`,
`debris_end`, per-joint tracking error — and the predicate is an ordinary `WHERE`
clause over those columns:

```bash
uv run -m curation --src episodes/<dataset> \
    --where "pct_dropped < 25 AND worst_gap_ms < 300"
```

The default is `pct_dropped < 40 AND worst_gap_ms < 500`. The clause is written
into the manifest beside the episode list, so "which episodes did v1 train on"
has an exact answer instead of a folder somebody copied by hand.

**A panel of detectors.** Each one answers a concrete question and explains
itself in a sentence you can check against the footage.

| detector | what it measures | default |
|---|---|---|
| `capture_stall` | a gap in the recording with no data in it at all | on |
| `truncated` | far shorter than any complete demonstration in the corpus | on |
| `task_not_completed` | yellow debris still on the table when the episode ends | off |
| `debris_outside_basket` | a piece at rest, outside the basket, nobody came back for | off |

{% capture rig %}
The first two measure the recorder and transfer to any rig. The last two read
yellow pixels off the top camera and were calibrated against winnow's own
sweeping-pasta setup — its own robustness audit found the chroma gates change
their verdict under a 25% perturbation. Turn them on with
`--detectors all` only if your task genuinely looks like that one, and check
what they flag before you believe it.
{% endcapture %}
{% include callout.html type="warn" title="Two of these are rig-specific" body=rig %}

Pick explicitly with a comma list, or turn the panel off entirely and curate on
the predicate alone:

```bash
uv run -m curation --src episodes/<dataset> --detectors capture_stall
uv run -m curation --src episodes/<dataset> --detectors none
```

## Reading the decision

```text
kept 7 of 10 episodes
rejected:
  episode_0006: failed `pct_dropped < 40 AND worst_gap_ms < 500` (pct_dropped=56.8, ...)
  episode_0007: capture_stall: a 1200 ms gap with no data recorded at all
  episode_0008: truncated: only 2 seconds, far shorter than any complete demonstration
```

Every rejection carries the numbers that caused it, so it can be argued with.
`--list` reprints the decision without re-running anything.

A flag is a claim, not a verdict — go and look at the ones you doubt:

```bash
uv run -m curation --src episodes/<dataset> --view-rejected   # only the rejects
uv run -m curation --src episodes/<dataset> --view            # the whole corpus
```

{% capture video %}
The recorder writes MPEG-4 Part 2, which Rerun's `AssetVideo` refuses to load,
so the viewer shows the signals without the footage. Add `--transcode` to
re-encode to H.264 first. It is slow and only affects what you can see — the
metrics and the detectors never needed it.
{% endcapture %}
{% include callout.html type="info" title="Add --transcode to see the video" body=video %}

## The decision travels with the data

`convert_to_lerobot.py` looks for `curation.json` next to the episodes, converts
only what it kept, and copies the manifest into the dataset directory — so it is
uploaded to the Hub with everything else. The provenance of a training run stops
being folklore.

| Flag | Effect |
|---|---|
| `--curation auto` | use `curation.json` if it is there, warn if it is not (default) |
| `--curation require` | refuse to convert an untriaged corpus |
| `--curation off` | convert every episode |
| `--curation-manifest <path>` | read the decision from somewhere else |

`push_dataset.py` prints what it is about to publish, and
`--require-curation` refuses to upload a dataset that was never triaged.

{% capture expect %}
`[curate] vision: running` through each stage, then `N of M episodes satisfy:
<your predicate>`, the kept count, and the reason for every rejection. The
first run on a corpus is the slow one — it decodes every video and writes an
`.rrd` per episode. Later runs reuse both.
{% endcapture %}
{% include callout.html type="expect" title="What you should see" body=expect %}

## When it will not run

**`winnow is not checked out`** — the submodule is missing. Run
`git submodule update --init third_party/winnow`.

**`every episode needs all three cameras and its data.npz`** — the recorder only
writes an `mp4` for a camera that delivered frames, and winnow's per-frame scan
opens all three by name. Move the incomplete recordings out of the dataset
directory; they were not going to be usable demonstrations anyway.

**`episodes declare fps N`** — winnow's dropped-tick threshold is hardwired to
15 Hz. On a rig recording at another rate, `pct_dropped` is measured against the
wrong period, so set your predicate against `true_hz` and `worst_gap_ms`
instead.

**`nothing ingested`** — the pipeline stopped before the `.rrd` files were
written. The stage that failed printed why; `--refresh` re-runs it.
