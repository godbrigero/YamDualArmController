"""GPU HTTP server for allenai/MolmoAct2-BimanualYAM.

Run this file on the cloud GPU.  The robot-side process sends JPEG observations
and receives absolute 14-dimensional action chunks in robot scale.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import numpy as np
import torch
from huggingface_hub import snapshot_download
from PIL import Image
from transformers import AutoModelForImageTextToText, AutoProcessor

from autonomous.policies import ACTION_DIM, CAMERA_ROLES


def _resolve_model(model_id: str) -> str:
    local_path = Path(model_id).expanduser()
    return str(local_path) if local_path.exists() else snapshot_download(repo_id=model_id)


def _patch_bfloat16_modeling(model_dir: str) -> None:
    """Apply Ai2's published no-op-safe bfloat16 compatibility fixes."""
    path = Path(model_dir) / "modeling_molmoact2.py"
    if not path.is_file():
        return
    source = path.read_text(encoding="utf-8")
    replacements = (
        (
            "device=device,\n            dtype=torch.float32,\n            generator=generator,",
            "device=device,\n            dtype=source_tensor.dtype,  # patched_bf16_dtype\n"
            "            generator=generator,",
            "patched_bf16_dtype",
        ),
        (
            "return value.detach().cpu().numpy().astype(np.float32, copy=False)",
            "return value.detach().cpu().float().numpy().astype(np.float32, copy=False)"
            "  # patched_bf16_to_array",
            "patched_bf16_to_array",
        ),
    )
    updated = source
    for needle, replacement, marker in replacements:
        if marker not in updated and needle in updated:
            updated = updated.replace(needle, replacement, 1)
    if updated != source:
        path.write_text(updated, encoding="utf-8")


class MolmoAct2Runner:
    def __init__(
        self,
        model_id: str,
        device: str,
        dtype_name: str,
        num_steps: int,
        cuda_graph: bool,
    ) -> None:
        dtype = getattr(torch, dtype_name)
        model_dir = _resolve_model(model_id)
        if dtype == torch.bfloat16:
            _patch_bfloat16_modeling(model_dir)
        self._torch = torch
        self._device = device
        self._dtype = dtype
        self._num_steps = num_steps
        self._cuda_graph = cuda_graph
        self._processor = AutoProcessor.from_pretrained(
            model_dir,
            trust_remote_code=True,
            extra_special_tokens={},
        )
        self._model = (
            AutoModelForImageTextToText.from_pretrained(
                model_dir,
                trust_remote_code=True,
                torch_dtype=dtype,
            )
            .to(device)
            .eval()
        )
        target_dtype = next(self._model.parameters()).dtype

        def move_and_cast(
            inputs: Any, destination: Any, target: torch.dtype = target_dtype
        ) -> dict[str, Any]:
            values: dict[str, Any] = {}
            for key, value in inputs.items():
                if torch.is_tensor(value):
                    value = value.to(destination)
                    if value.is_floating_point() and value.dtype != target:
                        value = value.to(target)
                values[key] = value
            return values

        self._model._move_inputs_to_device = move_and_cast
        self._lock = threading.Lock()

    @staticmethod
    def _decode_image(encoded: str):
        return Image.open(io.BytesIO(base64.b64decode(encoded, validate=True))).convert(
            "RGB"
        )

    def predict(self, payload: dict) -> list[list[float]]:
        state = np.asarray(payload["state"], dtype=np.float32)
        if state.shape != (ACTION_DIM,) or not np.isfinite(state).all():
            raise ValueError(f"state must contain {ACTION_DIM} finite values")
        images_by_role = payload["images"]
        images = [self._decode_image(images_by_role[role]) for role in CAMERA_ROLES]
        task = str(payload["task"]).strip()
        if not task:
            raise ValueError("task must not be empty")

        torch = self._torch
        autocast = (
            torch.autocast(device_type="cuda", dtype=self._dtype)
            if self._device.startswith("cuda") and self._dtype != torch.float32
            else torch.no_grad()
        )
        with self._lock, torch.inference_mode(), autocast:
            output = self._model.predict_action(
                processor=self._processor,
                images=images,  # Model contract: top, left, right.
                task=task,
                state=state,
                norm_tag="yam_dual_molmoact2",
                inference_action_mode="continuous",
                enable_depth_reasoning=False,
                num_steps=self._num_steps,
                normalize_language=True,
                enable_cuda_graph=self._cuda_graph,
            )
        actions = np.asarray(output.actions, dtype=np.float32)
        if actions.ndim == 3 and actions.shape[0] == 1:
            actions = actions[0]
        if actions.ndim == 1:
            actions = actions[None, :]
        if (
            actions.ndim != 2
            or actions.shape[1] != ACTION_DIM
            or not np.isfinite(actions).all()
        ):
            raise RuntimeError(f"model returned invalid action shape {actions.shape}")
        return actions.tolist()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Serve MolmoAct2 BimanualYAM inference"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--model", default="allenai/MolmoAct2-BimanualYAM")
    parser.add_argument("--device", default="cuda")
    parser.add_argument(
        "--dtype", choices=("float32", "bfloat16", "float16"), default="bfloat16"
    )
    parser.add_argument("--num-steps", type=int, default=10)
    parser.add_argument("--cuda-graph", action="store_true")
    parser.add_argument(
        "--token-env",
        default="YAM_VLA_TOKEN",
        help="environment variable containing the bearer token; empty means no authentication",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runner = MolmoAct2Runner(
        args.model, args.device, args.dtype, args.num_steps, args.cuda_graph
    )
    expected_token = os.environ.get(args.token_env) if args.token_env else None

    class Handler(BaseHTTPRequestHandler):
        def _json(self, status: int, value: dict) -> None:
            body = json.dumps(value).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._json(200, {"status": "ok"})
            else:
                self._json(404, {"error": "not found"})

        def do_POST(self) -> None:  # noqa: N802
            if self.path != "/predict":
                self._json(404, {"error": "not found"})
                return
            if (
                expected_token
                and self.headers.get("Authorization") != f"Bearer {expected_token}"
            ):
                self._json(401, {"error": "unauthorized"})
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if length <= 0 or length > 20_000_000:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length))
                self._json(200, {"actions": runner.predict(payload)})
            except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
            except Exception as exc:
                self._json(500, {"error": f"inference failed: {exc}"})

        def log_message(self, fmt: str, *values: object) -> None:
            print(f"{self.client_address[0]} - {fmt % values}", flush=True)

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"MolmoAct2 server listening on http://{args.host}:{args.port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
