#!/bin/bash

echo "[flux-fill-inpaint] Container startup..."

# Start ComfyUI in the background first (fast startup, no model DL blocking)
echo "[flux-fill-inpaint] Starting ComfyUI..."
python /ComfyUI/main.py --listen --disable-auto-launch &
COMFYUI_PID=$!

# Download FLUX.1 Fill model in the background (non-blocking)
MODEL_PATH="/ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors"
if [ ! -s "$MODEL_PATH" ]; then
    if [ -n "$HF_TOKEN" ]; then
        echo "[flux-fill-inpaint] Background-downloading FLUX.1 Fill [dev] (~23 GB)..."
        mkdir -p "$(dirname "$MODEL_PATH")"
        (
            huggingface-cli download black-forest-labs/FLUX.1-Fill-dev \
                flux1-fill-dev.safetensors \
                --local-dir /ComfyUI/models/diffusion_models \
                --token "$HF_TOKEN" && \
            echo "[flux-fill-inpaint] Model download complete."
        ) &
    else
        echo "[flux-fill-inpaint] WARNING: HF_TOKEN not set — model will not be downloaded."
    fi
else
    echo "[flux-fill-inpaint] FLUX.1 Fill [dev] model already present."
fi

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
