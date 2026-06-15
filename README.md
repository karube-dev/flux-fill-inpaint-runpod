# FLUX.1 Fill Inpainting — RunPod Serverless

Image inpainting worker built on **FLUX.1 Fill [dev]** and **ComfyUI**, packaged
for RunPod Serverless. Designed to be chained with the
[`Wan_Animate_Runpod_hub`](https://console.runpod.io/hub/wlsdml1114/Wan_Animate_Runpod_hub)
endpoint (inpaint → animate pipeline).

```
┌─ Local Gradio UI ─┐      ┌─ RunPod Serverless ─────────────┐
│                   │      │                                  │
│  image + mask     │ ───→ │  FLUX.1 Fill [dev]   ── image   │
│  + prompt         │      │                                  │
│                   │      │  Wan2.2-Animate-14B  ── video   │
└───────────────────┘      └──────────────────────────────────┘
```

---

## Project layout

```
flux-fill-inpaint-runpod/
├── Dockerfile          # CUDA 12.4 + ComfyUI + FLUX Fill models
├── handler.py          # RunPod Serverless handler
├── entrypoint.sh       # Starts ComfyUI, then the handler
├── inpaint_api.json    # ComfyUI workflow (FLUX Fill inpaint)
├── .runpod/hub.json    # RunPod Hub metadata
└── README.md
```

---

## API

### Request

```json
{
  "input": {
    "image_base64": "data:image/png;base64,...",
    "mask_base64":  "data:image/png;base64,...",   // optional
    "prompt":       "a beautiful sunset sky, photorealistic",
    "negative_prompt": "",
    "seed":         12345,
    "steps":        28,
    "cfg":          1.0,
    "sampler_name": "euler",
    "scheduler":    "simple",
    "denoise":      1.0
  }
}
```

Input resolution rules (all three of `image_path`, `image_url`, `image_base64`
work — use exactly one):

| Field | Description |
|---|---|
| `image_path` | A file already inside the container (e.g. `/runpod-volume/foo.png`) |
| `image_url`  | An http(s) URL — downloaded with `wget` |
| `image_base64` | Base64 (with or without `data:image/png;base64,` prefix) |

If you supply a `mask_*` field, the handler composites the mask into the
image's alpha channel so that ComfyUI's `LoadImage` node reads it as the
inpaint mask. If you only provide an image, the alpha channel of that image
is used as the mask directly.

### Response

```json
{
  "image":    "base64-encoded PNG, no data: prefix",
  "filename": "ComfyUI_00001_.png",
  "seed":     12345,
  "prompt":   "..."
}
```

---

## Build & deploy

### 1. Push to a GitHub repo

```bash
cd flux-fill-inpaint-runpod
git init
git add .
git commit -m "Initial FLUX Fill inpaint serverless worker"
gh repo create flux-fill-inpaint-runpod --public --source=. --push
```

### 2. Build the Docker image with HF_TOKEN

`FLUX.1 Fill [dev]` is a gated model. You must accept the license at
<https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev> and create a
Hugging Face access token.

```bash
docker build --build-arg HF_TOKEN=hf_xxxxxxxxxxxx -t flux-fill-inpaint:latest .
```

If you'd rather skip building the gated model in the image, leave out
`HF_TOKEN` and instead put `flux1-fill-dev.safetensors` on a RunPod Network
Volume at:

```
/ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors
```

(or any equivalent path the container can read at runtime — you would need
to add a small `cp` step in `entrypoint.sh`).

### 3. Deploy to RunPod Serverless

* **RunPod Console → Serverless → New Endpoint**
* **Container Image**: point to your pushed image (Docker Hub / GHCR /
  RunPod's own registry)
* **GPU**: A100 80GB (or A6000 48GB minimum; FLUX Fill bf16 needs ~24 GB VRAM
  plus overhead)
* **Container Disk**: ≥60 GB (models total ~33 GB)
* **Idle Timeout**: 5 s (keep it warm for chained calls)
* **Max Workers**: 1–3 depending on traffic

### 4. Smoke test

```bash
curl -X POST https://api.runpod.ai/v2/<endpoint_id>/runsync \
  -H "Authorization: Bearer $RUNPOD_API_KEY" \
  -H "Content-Type: application/json" \
  -d @test_request.json
```

---

## Client (Python) — chained with WanAnimate

```python
import base64, requests

API_KEY    = "your-runpod-key"
INPAINT    = "https://api.runpod.ai/v2/<id-inpaint>/runsync"
ANIMATE    = "https://api.runpod.ai/v2/<id-wananimate>/runsync"
HEADERS    = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}

with open("input.png", "rb") as fh:
    image_b64 = base64.b64encode(fh.read()).decode()
with open("mask.png", "rb") as fh:
    mask_b64 = base64.b64encode(fh.read()).decode()

# Step 1: inpaint
inpaint = requests.post(INPAINT, headers=HEADERS, json={
    "input": {
        "image_base64": image_b64,
        "mask_base64":  mask_b64,
        "prompt":       "a beautiful sunset sky, photorealistic",
        "seed":         42,
    }
}).json()

inpainted_b64 = inpaint["output"]["image"]   # base64 PNG

# Step 2: animate
animate = requests.post(ANIMATE, headers=HEADERS, json={
    "input": {
        "image_base64": inpainted_b64,
        "video_base64": base64.b64encode(open("ref.mp4","rb").read()).decode(),
        "prompt":       "A person turning toward a sunset, soft cinematic light",
        "seed":         42,
        "width": 832,
        "height": 480,
        "fps": 16,
        "cfg": 1.0,
        "steps": 6,
    }
}).json()

with open("output.mp4", "wb") as fh:
    fh.write(base64.b64decode(animate["output"]["video"]))
```

---

## Notes

* **Cold start**: ~60 s the first time (ComfyUI boots, model loads).
  Subsequent requests on a warm worker return in ~3–8 s for a 28-step
  inpaint at 1024×1024.
* **GPU recommendation**: A100 80GB is the sweet spot. The 24 GB RTX 4090
  *can* fit FLUX Fill with FP8 + offloading, but is slower.
* **License**: FLUX.1 Fill [dev] is non-commercial. If you need
  commercial use, license it from <https://bfl.ai/pricing/licensing>.
