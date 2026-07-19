#!/usr/bin/env python3
"""Convert our mp4+npz episodes into a LeRobotDataset (and optionally push to HF).

Run with the conda lerobot python:
    /home/shiv/miniforge3/envs/lerobot/bin/python convert_to_lerobot.py \
        --src episodes/default --repo-id Shivakumr/yam_default [--limit 2] [--push] [--private]

--format act (default) keeps the wrist_1/wrist_2 camera keys used by the ACT
pipeline; --format molmoact2 emits observation.images.{top,left,right} and
robot_type bi_yam_follower for MolmoAct2 fine-tuning (yam_fold mixture in
molmoact2/experiments/launch_scripts/data_mixtures.py).

If the source directory carries a `curation.json` — written by
`uv run -m curation --src episodes/<dataset>`, which triages the corpus through
winnow's Rerun catalog — only the episodes it kept are converted, and the
manifest is copied into the dataset so the Hub records which recordings the
policy was trained on and why the rest were dropped. `--curation off` converts
everything; `--curation require` refuses to run without a manifest.
"""
import argparse
import glob
import os
import shutil
import sys

import cv2
import numpy as np
from lerobot.datasets.lerobot_dataset import LeRobotDataset

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    from curation.manifest import filter_episodes, load_manifest
except ImportError:  # copied out of the project on its own
    filter_episodes = load_manifest = None

CAMS = ["top", "wrist_1", "wrist_2"]
# dataset camera keys per output format; source mp4 names are always CAMS.
# molmoact2: the yam_fold mixture and the BimanualYAM checkpoint's norm stats
# expect observation.images.{top,left,right}. On this rig wrist_1 films the
# right (can1) arm and wrist_2 the left (can0) arm.
CAM_KEYS = {
    "act": {"top": "top", "wrist_1": "wrist_1", "wrist_2": "wrist_2"},
    "molmoact2": {"top": "top", "wrist_1": "right", "wrist_2": "left"},
}
ROBOT_TYPES = {"act": "yam_bimanual_so101_leader", "molmoact2": "bi_yam_follower"}
# state/action layout: recorder concatenates can0 then can1, each 6 joints + gripper
STATE_NAMES = [f"{ch}_{j}" for ch in ("can0", "can1")
               for j in ("j1", "j2", "j3", "j4", "j5", "j6", "gripper")]


def build_features(h, w, cam_keys):
    feats = {}
    for c in CAMS:
        feats[f"observation.images.{cam_keys[c]}"] = {
            "dtype": "video", "shape": (h, w, 3),
            "names": ["height", "width", "channels"],
        }
    feats["observation.state"] = {"dtype": "float32", "shape": (len(STATE_NAMES),), "names": STATE_NAMES}
    feats["action"] = {"dtype": "float32", "shape": (len(STATE_NAMES),), "names": STATE_NAMES}
    return feats


def resolve_curation(args):
    """The triage decision to honour, and where it came from. (None, None) if none."""
    if load_manifest is None:
        if args.curation == "require":
            raise SystemExit(
                "the curation package is not importable, so no manifest can be read. "
                "Run this from a checkout with curation/ beside leader_yam_bridge/, "
                "or pass --curation off."
            )
        print("curation package not importable — converting every episode.")
        return None, None

    source = args.curation_manifest or args.src
    manifest = None if args.curation == "off" else load_manifest(source)
    if manifest is None:
        if args.curation == "require":
            raise SystemExit(
                f"no curation.json for {args.src}. Triage the corpus first:\n"
                f"    uv run -m curation --src {args.src}\n"
                "or pass --curation off to convert every episode regardless."
            )
        if args.curation == "auto":
            print(f"no curation.json in {source} — converting every episode.")
            print(f"    uv run -m curation --src {args.src}    # triage first")
        return None, None
    return manifest, os.path.join(source, "curation.json") if os.path.isdir(source) else source


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="episodes/default")
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--fps", type=int, default=15)
    ap.add_argument("--task", default="bimanual teleoperation")
    ap.add_argument("--format", choices=sorted(CAM_KEYS), default="act",
                    help="dataset schema: act (wrist_1/wrist_2 keys) or molmoact2 (left/right keys for the yam_fold fine-tune mixture)")
    ap.add_argument("--robot-type", default=None,
                    help="override robot_type (default depends on --format)")
    ap.add_argument("--limit", type=int, default=0, help="only convert first N episodes (0 = all)")
    ap.add_argument("--episodes", default="", help="only these episode indices, e.g. 7,8,12-19")
    ap.add_argument("--curation", choices=("auto", "require", "off"), default="auto",
                    help="auto: use curation.json if present; require: fail without it; "
                         "off: convert every episode")
    ap.add_argument("--curation-manifest", default=None,
                    help="path to a curation.json elsewhere (default: <src>/curation.json)")
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--private", action="store_true")
    args = ap.parse_args()
    cam_keys = CAM_KEYS[args.format]
    robot_type = args.robot_type or ROBOT_TYPES[args.format]

    eps = sorted(glob.glob(os.path.join(args.src, "episode_*")))
    if args.episodes:
        keep = set()
        for part in args.episodes.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, b = part.split("-")
                keep.update(range(int(a), int(b) + 1))
            else:
                keep.add(int(part))
        eps = [e for e in eps if int(os.path.basename(e).split("_")[1]) in keep]
        print(f"filtering to {len(eps)} episodes: {sorted(keep)}")
    if not eps:
        print(f"no episodes in {args.src}")
        return

    manifest, manifest_src = resolve_curation(args)
    if manifest is not None:
        eps, skipped = filter_episodes(eps, manifest)
        print(f"curation ({os.path.relpath(manifest_src)}): {manifest.summary()}")
        print(f"  query: {manifest.query}")
        for path in skipped:
            name = os.path.basename(path)
            print(f"  skipping {name}: {'; '.join(manifest.rejected.get(name, ['not kept']))}")
        if not eps:
            print("curation rejected every episode; nothing to convert")
            return

    if args.limit:
        eps = eps[: args.limit]
    # resolution from the first video
    cap = cv2.VideoCapture(os.path.join(eps[0], f"{CAMS[0]}.mp4"))
    w, h = int(cap.get(3)), int(cap.get(4))
    cap.release()
    print(f"converting {len(eps)} episodes @ {w}x{h}, fps={args.fps} -> {args.repo_id}")

    # fresh local dataset dir
    root = os.path.expanduser(f"~/.cache/huggingface/lerobot/{args.repo_id}")
    if os.path.exists(root):
        print(f"removing existing local dataset at {root}")
        shutil.rmtree(root)

    ds = LeRobotDataset.create(
        repo_id=args.repo_id, fps=args.fps, features=build_features(h, w, cam_keys),
        robot_type=robot_type, use_videos=True,
    )
    # where it actually landed, which is not the guess above under HF_LEROBOT_HOME
    root = str(getattr(ds, "root", root))

    for ei, ep in enumerate(eps):
        z = np.load(os.path.join(ep, "data.npz"))
        state, action = z["state"], z["action"]
        caps = {c: cv2.VideoCapture(os.path.join(ep, f"{c}.mp4")) for c in CAMS}
        n = len(state)
        written = 0
        for i in range(n):
            imgs = {}
            ok = True
            for c in CAMS:
                r, bgr = caps[c].read()
                if not r:
                    ok = False
                    break
                imgs[c] = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            if not ok:
                break
            frame = {"task": args.task,
                     "observation.state": state[i].astype(np.float32),
                     "action": action[i].astype(np.float32)}
            for c in CAMS:
                frame[f"observation.images.{cam_keys[c]}"] = imgs[c]
            ds.add_frame(frame)
            written += 1
        for cap in caps.values():
            cap.release()
        ds.save_episode()
        print(f"  [{ei+1}/{len(eps)}] {os.path.basename(ep)}: {written} frames")

    ds.finalize()

    # the decision travels with the data: "which episodes did this train on" has
    # an answer on the Hub, not just on the machine that ran the conversion
    if manifest_src:
        shutil.copy(manifest_src, os.path.join(root, "curation.json"))
        print(f"recorded curation.json in the dataset ({manifest.summary()})")

    print(f"done. local dataset: {root}")

    if args.push:
        print(f"pushing to HF hub as {args.repo_id} (private={args.private})...")
        ds.push_to_hub(private=args.private, tags=["yam", "so101", args.format, "bimanual"])
        print(f"pushed: https://huggingface.co/datasets/{args.repo_id}")


if __name__ == "__main__":
    main()
