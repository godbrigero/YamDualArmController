#!/usr/bin/env python3
"""Resumable push of a local LeRobotDataset to the HF Hub.

Uses upload_large_folder (multi-threaded, resumable, retries on flaky networks).
Safe to re-run — it skips already-uploaded files and continues.

    /home/shiv/miniforge3/envs/lerobot/bin/python push_dataset.py \
        --repo-id Shivakumr/yams [--private]

The dataset it uploads is whatever conversion produced, so curation happens
upstream in `convert_to_lerobot.py`. This script reports the `curation.json`
conversion left behind, and `--require-curation` refuses to publish a dataset
that was never triaged.
"""
import argparse
import os
import sys

from huggingface_hub import HfApi, upload_large_folder

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
try:
    from curation.manifest import load_manifest
except ImportError:
    # copied out of the project on its own. Read the manifest with the stdlib
    # rather than reporting a missing one, which would be a false statement
    # about the dataset and would make --require-curation refuse a curated push.
    import json

    def load_manifest(local):
        try:
            with open(os.path.join(local, "curation.json")) as handle:
                raw = json.load(handle)
        except (OSError, ValueError):
            return None
        return argparse.Namespace(
            kept=raw.get("kept", []),
            rejected=raw.get("rejected", {}),
            query=raw.get("query", ""),
            summary=lambda: f"kept {len(raw.get('kept', []))} of "
                            f"{len(raw.get('kept', [])) + len(raw.get('rejected', {}))} episodes",
        )


def report_curation(local, require):
    manifest = load_manifest(local)
    if manifest is None:
        message = (f"{local} carries no curation.json — every recorded episode is in it, "
                   "including any the detectors would have rejected.\n"
                   "  uv run -m curation --src episodes/<dataset>   # then re-convert")
        if require:
            raise SystemExit(f"refusing to push: {message}")
        print(f"warning: {message}", flush=True)
        return
    print(f"curated dataset: {manifest.summary()} (query: {manifest.query})", flush=True)
    if manifest.rejected:
        print("  excluded: " + ", ".join(sorted(manifest.rejected)), flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-id", required=True)
    ap.add_argument("--private", action="store_true")
    ap.add_argument("--local", default=None)
    ap.add_argument("--require-curation", action="store_true",
                    help="refuse to push a dataset that was built without triage")
    args = ap.parse_args()

    local = args.local or os.path.expanduser(f"~/.cache/huggingface/lerobot/{args.repo_id}")
    if not os.path.isdir(local):
        raise SystemExit(f"local dataset not found: {local}")

    report_curation(local, args.require_curation)

    api = HfApi()
    api.create_repo(args.repo_id, repo_type="dataset", exist_ok=True, private=args.private)
    print(f"uploading {local} -> {args.repo_id} (resumable)...", flush=True)
    upload_large_folder(folder_path=local, repo_id=args.repo_id, repo_type="dataset")
    print(f"DONE: https://huggingface.co/datasets/{args.repo_id}", flush=True)


if __name__ == "__main__":
    main()
