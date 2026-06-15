#!/bin/bash
set -e

echo "[flux-fill-inpaint] Container startup..."

# Ensure the FLUX.1 Fill model is present.
# HF_TOKEN must be provided as a RunPod Environment Variable.
MODEL_PATH="/ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors"
if [ ! -s "$MODEL_PATH" ]; then
    if [ -z "$HF_TOKEN" ]; then
        echo "[flux-fill-inpaint] ERROR: HF_TOKEN env var is not set."
        echo "[flux-fill-inpaint] Set HF_TOKEN in RunPod Endpoint Environment Variables."
        echo "[flux-fill-inpaint] Make sure you have accepted the license at:"
        echo "[flux-fill-inpaint]   https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev"
        exit 1
    fi
    echo "[flux-fill-inpaint] Downloading FLUX.1 Fill [dev] (~23 GB)..."
    mkdir -p "$(dirname "$MODEL_PATH")"
    if ! huggingface-cli download black-forest-labs/FLUX.1-Fill-dev \
            flux1-fill-dev.safetensors \
            --local-dir /ComfyUI/models/diffusion_models \
            --token "$HF_TOKEN"; then
        echo "[flux-fill-inpaint] ERROR: model download failed. Check HF_TOKEN validity."
        exit 1
    fi
    echo "[flux-fill-inpaint] Model download complete."
else
    echo "[flux-fill-inpaint] FLUX.1 Fill [dev] model already present."
fi

# Start ComfyUI in the background
echo "[flux-fill-inpaint] Starting ComfyUI..."
python /ComfyUI/main.py --listen --disable-auto-launch &

COMFYUI_PID=$!

# Wait for the ComfyUI HTTP endpoint to come up
echo "[flux-fill-inpaint] Waiting for ComfyUI to be ready..."
max_wait=180
wait_count=0
while [ $wait_count -lt $max_wait ]; do
    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "[flux-fill-inpaint] ComfyUI is ready."
        break
    fi
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "[flux-fill-inpaint] ERROR: ComfyUI failed to start within ${max_wait}s"
    kill $COMFYUI_PID 2>/dev/null || true
    exit 1
fi

# Start the RunPod handler in the foreground
echo "[flux-fill-inpaint] Starting RunPod handler..."
exec python /worker/handler.py
