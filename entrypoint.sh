#!/bin/bash
echo "[flux-fill-inpaint] Container startup..."
echo "[flux-fill-inpaint] RUNPOD_WEBHOOK_GET_JOB=${RUNPOD_WEBHOOK_GET_JOB:-NOT SET}"

# Start ComfyUI FIRST (fast without models)
echo "[flux-fill-inpaint] Starting ComfyUI..."
python /ComfyUI/main.py --listen --disable-auto-launch &
COMFYUI_PID=$!

# Download models in the background (can take 5-10 min)
(
    echo "[flux-fill-inpaint] Background: downloading models..."
    wget -q "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" \
        -O /ComfyUI/models/text_encoders/t5xxl_fp16.safetensors &
    wget -q "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
        -O /ComfyUI/models/text_encoders/clip_l.safetensors &
    wget -q "https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" \
        -O /ComfyUI/models/vae/ae.safetensors &
    wait

    MODEL_PATH="/ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors"
    if [ ! -s "$MODEL_PATH" ] && [ -n "$HF_TOKEN" ]; then
        echo "[flux-fill-inpaint] Background: downloading FLUX.1 Fill [dev] (~23 GB)..."
        huggingface-cli download black-forest-labs/FLUX.1-Fill-dev \
            flux1-fill-dev.safetensors \
            --local-dir /ComfyUI/models/diffusion_models \
            --token "$HF_TOKEN" && \
        echo "[flux-fill-inpaint] Background: all models downloaded."
    fi
) &

MODEL_DL_PID=$!

# Wait for ComfyUI to be ready
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

# Start the RunPod handler (will wait for RUNPOD_WEBHOOK_GET_JOB internally)
echo "[flux-fill-inpaint] Starting RunPod handler..."
exec python /worker/handler.py
