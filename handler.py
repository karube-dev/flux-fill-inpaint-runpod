"""
FLUX.1 Fill [dev] inpainting worker for RunPod Serverless.

Communicates with a ComfyUI instance over WebSocket. The expected workflow
lives at /inpaint_api.json inside the container and contains placeholder
node ids/names that this script wires up at request time.
"""
import os
import json
import time
import uuid
import base64
import binascii
import logging
import subprocess
import urllib.parse
import urllib.request

import runpod
import websocket  # provided by `pip install websocket-client`

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SERVER_ADDRESS = os.getenv("SERVER_ADDRESS", "127.0.0.1")
WORKFLOW_PATH = os.getenv("WORKFLOW_PATH", "/inpaint_api.json")
COMFYUI_INPUT_DIR = os.getenv("COMFYUI_INPUT_DIR", "/ComfyUI/input")
COMFYUI_OUTPUT_DIR = os.getenv("COMFYUI_OUTPUT_DIR", "/ComfyUI/output")
CLIENT_ID = str(uuid.uuid4())


# ---------------------------------------------------------------------------
# I/O helpers (path / url / base64)
# ---------------------------------------------------------------------------
def _save_base64_to_file(data: str, out_path: str) -> str:
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    decoded = base64.b64decode(data)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(decoded)
    return out_path


def _download_url_to_file(url: str, out_path: str) -> str:
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result = subprocess.run(
        ["wget", "-O", out_path, "--no-verbose", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wget failed: {result.stderr}")
    return out_path


def resolve_input(value, dest_dir: str, dest_filename: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"Expected string input, got {type(value).__name__}")

    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.abspath(os.path.join(dest_dir, dest_filename))

    if os.path.isfile(value):
        return value

    if value.startswith("http://") or value.startswith("https://"):
        return _download_url_to_file(value, target)

    try:
        return _save_base64_to_file(value, target)
    except (binascii.Error, ValueError) as exc:
        raise ValueError(
            "Input is not a local file, URL, or valid base64 string"
        ) from exc


# ---------------------------------------------------------------------------
# ComfyUI websocket plumbing
# ---------------------------------------------------------------------------
def queue_prompt(prompt: dict) -> str:
    url = f"http://{SERVER_ADDRESS}:8188/prompt"
    logger.info("Queuing prompt to %s", url)
    body = json.dumps({"prompt": prompt, "client_id": CLIENT_ID}).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        resp_body = resp.read().decode("utf-8")
        if resp.status != 200:
            raise RuntimeError(f"ComfyUI returned {resp.status}: {resp_body[:500]}")
        data = json.loads(resp_body)
        if "prompt_id" not in data:
            raise RuntimeError(f"ComfyUI response missing prompt_id: {resp_body[:500]}")
        return data["prompt_id"]


def get_history(prompt_id: str) -> dict:
    url = f"http://{SERVER_ADDRESS}:8188/history/{prompt_id}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def wait_for_completion(prompt: dict, timeout: int = 1800) -> dict:
    prompt_id = queue_prompt(prompt)
    ws = websocket.WebSocket()
    ws.connect(f"ws://{SERVER_ADDRESS}:8188/ws?clientId={CLIENT_ID}")

    deadline = time.time() + timeout
    try:
        while time.time() < deadline:
            try:
                ws.settimeout(max(1, int(deadline - time.time())))
                msg = ws.recv()
            except websocket.WebSocketTimeoutException:
                raise TimeoutError("Timed out waiting for ComfyUI")

            if isinstance(msg, str):
                event = json.loads(msg)
                if event.get("type") == "executing":
                    data = event.get("data") or {}
                    if data.get("node") is None and data.get("prompt_id") == prompt_id:
                        return get_history(prompt_id)
    finally:
        ws.close()

    raise TimeoutError("ComfyUI execution did not finish in time")


def collect_outputs(history_entry: dict) -> list:
    results = []
    for node_id, node_output in (history_entry.get("outputs") or {}).items():
        for image in node_output.get("images", []):
            fullpath = image.get("fullpath") or os.path.join(
                COMFYUI_OUTPUT_DIR, image.get("filename", "")
            )
            with open(fullpath, "rb") as fh:
                results.append({
                    "node_id": node_id,
                    "filename": image.get("filename"),
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "output"),
                    "image_base64": base64.b64encode(fh.read()).decode("utf-8"),
                })
    return results


# ---------------------------------------------------------------------------
# Workflow wiring
# ---------------------------------------------------------------------------
def load_workflow() -> dict:
    with open(WORKFLOW_PATH, "r") as fh:
        return json.load(fh)


def build_prompt(
    workflow: dict,
    image_path: str,
    prompt_text: str,
    negative_text: str,
    seed: int,
    steps: int,
    cfg: float,
    sampler_name: str,
    scheduler: str,
    denoise: float,
) -> dict:
    prompt = json.loads(json.dumps(workflow))

    prompt["6"]["inputs"]["image"] = os.path.basename(image_path)

    prompt["7"]["inputs"]["text"] = prompt_text
    prompt["8"]["inputs"]["text"] = negative_text
    prompt["11"]["inputs"]["seed"] = int(seed)
    prompt["11"]["inputs"]["steps"] = int(steps)
    prompt["11"]["inputs"]["cfg"] = float(cfg)
    prompt["11"]["inputs"]["sampler_name"] = sampler_name
    prompt["11"]["inputs"]["scheduler"] = scheduler
    prompt["11"]["inputs"]["denoise"] = float(denoise)

    return prompt


# ---------------------------------------------------------------------------
# Lazy ComfyUI readiness check (called on first inference)
# ---------------------------------------------------------------------------
_COMFYUI_READY = False

def _wait_comfyui_ready(timeout: int = 300):
    global _COMFYUI_READY
    if _COMFYUI_READY:
        return
    logger.info("Waiting for ComfyUI to become ready (timeout=%ds)...", timeout)
    import requests as _requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = _requests.get(f"http://{SERVER_ADDRESS}:8188/", timeout=5)
            if resp.status_code == 200:
                _COMFYUI_READY = True
                logger.info("ComfyUI is ready.")
                return
        except Exception:
            pass
        time.sleep(2)
    raise RuntimeError(f"ComfyUI did not become ready within {timeout}s")


# ---------------------------------------------------------------------------
# RunPod entry point
# ---------------------------------------------------------------------------
def handler(job: dict) -> dict:
    job_input = job.get("input") or {}
    logger.info("Received job input keys: %s", list(job_input.keys()))

    _wait_comfyui_ready()

    image_field = next(
        (k for k in ("image_path", "image_url", "image_base64") if k in job_input),
        None,
    )
    if image_field is None:
        raise ValueError(
            "Image is required. Provide one of: image_path, image_url, image_base64"
        )

    tmp_dir = f"/tmp/inpaint_{uuid.uuid4().hex}"
    os.makedirs(tmp_dir, exist_ok=True)
    image_path = resolve_input(job_input[image_field], tmp_dir, "input.png")

    if any(k in job_input for k in ("mask_path", "mask_url", "mask_base64")):
        mask_field = next(
            k for k in ("mask_path", "mask_url", "mask_base64") if k in job_input
        )
        mask_path = resolve_input(job_input[mask_field], tmp_dir, "mask.png")
        image_path = _compose_alpha_mask(image_path, mask_path, tmp_dir)

    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Could not resolve input image at {image_path}")

    prompt_text = job_input.get("prompt", "high quality, detailed, seamless, natural")
    negative_text = job_input.get("negative_prompt", "")
    seed = int(job_input.get("seed", 12345))
    steps = int(job_input.get("steps", 28))
    cfg = float(job_input.get("cfg", 1.0))
    sampler_name = job_input.get("sampler_name", "euler")
    scheduler = job_input.get("scheduler", "simple")
    denoise = float(job_input.get("denoise", 1.0))

    comfy_input_target = os.path.join(COMFYUI_INPUT_DIR, os.path.basename(image_path))
    if os.path.abspath(image_path) != os.path.abspath(comfy_input_target):
        os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)
        with open(image_path, "rb") as src, open(comfy_input_target, "wb") as dst:
            dst.write(src.read())
        image_path = comfy_input_target

    workflow = load_workflow()
    prompt = build_prompt(
        workflow,
        image_path=image_path,
        prompt_text=prompt_text,
        negative_text=negative_text,
        seed=seed,
        steps=steps,
        cfg=cfg,
        sampler_name=sampler_name,
        scheduler=scheduler,
        denoise=denoise,
    )
    history = wait_for_completion(prompt)
    prompt_id = list(history.keys())[0]
    outputs = collect_outputs(history[prompt_id])

    if not outputs:
        return {"error": "ComfyUI finished but no image was produced."}

    first = outputs[0]
    return {
        "image": first["image_base64"],
        "filename": first["filename"],
        "seed": seed,
        "prompt": prompt_text,
    }


def _compose_alpha_mask(image_path: str, mask_path: str, work_dir: str) -> str:
    from PIL import Image

    img = Image.open(image_path).convert("RGBA")
    mask = Image.open(mask_path).convert("L")

    if mask.size != img.size:
        mask = mask.resize(img.size, Image.BILINEAR)

    mask = mask.point(lambda v: 255 if v > 128 else 0)

    r, g, b, _ = img.split()
    out = Image.merge("RGBA", (r, g, b, mask))
    target = os.path.abspath(os.path.join(work_dir, "composited.png"))
    out.save(target)
    return target


logger.info("Starting RunPod serverless worker...")
runpod.serverless.start({"handler": handler})
