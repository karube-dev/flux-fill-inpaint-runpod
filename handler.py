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
    """Decode a (possibly data-URL-prefixed) base64 string and write to disk."""
    if data.startswith("data:") and "," in data:
        data = data.split(",", 1)[1]
    decoded = base64.b64decode(data)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as fh:
        fh.write(decoded)
    return out_path


def _download_url_to_file(url: str, out_path: str) -> str:
    """Use wget to download a file to a local path."""
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    result = subprocess.run(
        ["wget", "-O", out_path, "--no-verbose", url],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"wget failed: {result.stderr}")
    return out_path


def resolve_input(value, dest_dir: str, dest_filename: str) -> str:
    """
    Accept one of:
      - a local path that already exists on disk
      - an http(s) URL
      - a base64-encoded string (with or without data: prefix)
    and return a local file path.
    """
    if not isinstance(value, str):
        raise TypeError(f"Expected string input, got {type(value).__name__}")

    os.makedirs(dest_dir, exist_ok=True)
    target = os.path.abspath(os.path.join(dest_dir, dest_filename))

    # 1. Already a local file?
    if os.path.isfile(value):
        return value

    # 2. URL?
    if value.startswith("http://") or value.startswith("https://"):
        return _download_url_to_file(value, target)

    # 3. Base64?
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
    req = urllib.request.Request(url, data=body)
    resp = json.loads(urllib.request.urlopen(req).read())
    return resp["prompt_id"]


def get_history(prompt_id: str) -> dict:
    url = f"http://{SERVER_ADDRESS}:8188/history/{prompt_id}"
    with urllib.request.urlopen(url) as resp:
        return json.loads(resp.read())


def wait_for_completion(prompt: dict, timeout: int = 1800) -> dict:
    """Send the workflow and block until ComfyUI reports completion."""
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
    """Pull every saved image (and gifs) from a completed execution."""
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
    """
    Wire input values into the workflow template. The node ids below match
    the static workflow shipped in /inpaint_api.json.
    """
    prompt = json.loads(json.dumps(workflow))  # deep copy

    # The ComfyUI LoadImage node expects the *basename* of a file in the
    # input directory (or a subfolder). We ensure the file is in the
    # input dir and use the basename.
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
# RunPod entry point
# ---------------------------------------------------------------------------
def handler(job: dict) -> dict:
    job_input = job.get("input") or {}
    logger.info("Received job input keys: %s", list(job_input.keys()))

    # ------------------------------------------------------------------ input
    image_field = next(
        (k for k in ("image_path", "image_url", "image_base64") if k in job_input),
        None,
    )
    if image_field is None:
        raise ValueError(
            "Image is required. Provide one of: image_path, image_url, image_base64"
        )

    # ComfyUI's LoadImage treats the alpha channel of a PNG as the mask.
    # Users either supply a PNG with a mask baked into alpha, or they
    # supply a separate mask via mask_base64 / mask_url / mask_path and we
    # composite it onto the image before handing it to ComfyUI.
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

    # ----------------------------------------------------------- parameters
    prompt_text = job_input.get("prompt", "high quality, detailed, seamless, natural")
    negative_text = job_input.get("negative_prompt", "")
    seed = int(job_input.get("seed", 12345))
    steps = int(job_input.get("steps", 28))
    cfg = float(job_input.get("cfg", 1.0))
    sampler_name = job_input.get("sampler_name", "euler")
    scheduler = job_input.get("scheduler", "simple")
    denoise = float(job_input.get("denoise", 1.0))

    # Also drop the prepared file into ComfyUI's input directory so the
    # LoadImage node can find it by basename.
    comfy_input_target = os.path.join(COMFYUI_INPUT_DIR, os.path.basename(image_path))
    if os.path.abspath(image_path) != os.path.abspath(comfy_input_target):
        os.makedirs(COMFYUI_INPUT_DIR, exist_ok=True)
        with open(image_path, "rb") as src, open(comfy_input_target, "wb") as dst:
            dst.write(src.read())
        image_path = comfy_input_target

    # ------------------------------------------------------------------ run
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
    """
    Combine an image and a single-channel mask PNG into one RGBA PNG whose
    alpha channel equals the mask. ComfyUI's LoadImage reads the alpha
    channel as the inpaint mask.
    """
    from PIL import Image

    img = Image.open(image_path).convert("RGBA")
    mask = Image.open(mask_path).convert("L")

    if mask.size != img.size:
        mask = mask.resize(img.size, Image.BILINEAR)

    # Threshold to clean up anti-aliased edges
    mask = mask.point(lambda v: 255 if v > 128 else 0)

    r, g, b, _ = img.split()
    out = Image.merge("RGBA", (r, g, b, mask))
    target = os.path.abspath(os.path.join(work_dir, "composited.png"))
    out.save(target)
    return target


def main():
    """
    Entry point with wait for RunPod platform env injection.
    On serverless, RUNPOD_WEBHOOK_GET_JOB must be set before
    runpod.serverless.start() is called, otherwise it enters local
    mode and exits immediately with code 1.
    """
    import sys as _sys, os as _os, time as _time

    logger.info("Waiting for RunPod platform env vars...")
    max_wait = 120
    waited = 0
    while waited < max_wait:
        job_url = _os.environ.get("RUNPOD_WEBHOOK_GET_JOB")
        if job_url:
            logger.info(f"Platform env vars detected after {waited:.0f}s")
            break
        _time.sleep(2)
        waited += 2
        if waited % 10 == 0:
            logger.info(f"Still waiting... ({waited:.0f}s)")

    if waited >= max_wait:
        logger.warning(
            "RUNPOD_WEBHOOK_GET_JOB not set after %ds — "
            "running in best-effort mode (may exit if no test_input.json)",
            max_wait,
        )

    runpod.serverless.start({"handler": handler})


if __name__ == "__main__":
    main()
