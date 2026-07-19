"""Modal deployment for MolmoAct2 BimanualYAM inference.

Configuration is read when ``modal deploy`` runs:

* ``YAM_VLA_MODEL``: Hugging Face ID or checkpoint path mounted at ``/models``.
* ``YAM_VLA_VOLUME``: Modal Volume containing/caching model weights.
* ``YAM_VLA_GPU``: Modal GPU type (default ``L40S``).
"""

from __future__ import annotations

import os

import modal


MODEL = os.environ.get("YAM_VLA_MODEL", "allenai/MolmoAct2-BimanualYAM")
VOLUME_NAME = os.environ.get("YAM_VLA_VOLUME", "yam-vla-models")
GPU = os.environ.get("YAM_VLA_GPU", "L40S")
MODEL_MOUNT = "/models"

image = (
    modal.Image.debian_slim(python_version="3.12")
    .pip_install(
        "fastapi[standard]",
        "huggingface_hub[hf_xet]",
        "numpy",
        "pillow",
        "scipy",
        "torch",
        "transformers",
    )
    .env(
        {
            "HF_HOME": f"{MODEL_MOUNT}/huggingface",
            "HF_XET_HIGH_PERFORMANCE": "1",
        }
    )
    .add_local_python_source("autonomous")
)

model_volume = modal.Volume.from_name(VOLUME_NAME, create_if_missing=True)
app = modal.App("yam-molmoact2-inference")

with image.imports():
    from autonomous.vla_server import MolmoAct2Runner


@app.cls(
    image=image,
    gpu=GPU,
    volumes={MODEL_MOUNT: model_volume},
    timeout=10 * 60,
    scaledown_window=5 * 60,
    max_containers=1,
)
class MolmoAct2Endpoint:
    @modal.enter()
    def load(self) -> None:
        self.runner = MolmoAct2Runner(
            model_id=MODEL,
            device="cuda",
            dtype_name="bfloat16",
            num_steps=10,
            cuda_graph=False,
        )

    @modal.fastapi_endpoint(method="POST", requires_proxy_auth=True)
    def predict(self, payload: dict) -> dict:
        return {"actions": self.runner.predict(payload)}
