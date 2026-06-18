#!/bin/bash
echo "[flux-fill-inpaint] Container startup..."
echo "[flux-fill-inpaint] RUNPOD_WEBHOOK_GET_JOB=${RUNPOD_WEBHOOK_GET_JOB:-NOT SET}"

# Start ComfyUI (fast without models)
echo "[flux-fill-inpaint] Starting ComfyUI..."
python /ComfyUI/main.py --listen --disable-auto-launch &
COMFYUI_PID=$!

# Download models in the background using huggingface-cli (HF_TOKEN required)
(
    echo "[flux-fill-inpaint] Background: downloading models with HF_TOKEN..."
    if [ -z "$HF_TOKEN" ]; then
        echo "[flux-fill-inpaint] ERROR: HF_TOKEN not set — cannot download gated models"
        exit 1
    fi

    # Text encoders (public)
    echo "[flux-fill-inpaint] Downloading t5xxl text encoder..."
    huggingface-cli download comfyanonymous/flux_text_encoders t5xxl_fp16.safetensors \
        --local-dir /ComfyUI/models/text_encoders --token "$HF_TOKEN" &
    echo "[flux-fill-inpaint] Downloading CLIP-L..."
    huggingface-cli download comfyanonymous/flux_text_encoders clip_l.safetensors \
        --local-dir /ComfyUI/models/text_encoders --token "$HF_TOKEN" &

    # VAE from FLUX.1-dev (gated)
    echo "[flux-fill-inpaint] Downloading FLUX VAE..."
    huggingface-cli download black-forest-labs/FLUX.1-dev ae.safetensors \
        --local-dir /ComfyUI/models/vae --token "$HF_TOKEN" &
    wait

    # FLUX.1 Fill [dev] diffusion model (~23 GB, gated)
    MODEL_PATH="/ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors"
    if [ ! -s "$MODEL_PATH" ]; then
        echo "[flux-fill-inpaint] Downloading FLUX.1 Fill [dev] (~23 GB)..."
        huggingface-cli download black-forest-labs/FLUX.1-Fill-dev \
            flux1-fill-dev.safetensors \
            --local-dir /ComfyUI/models/diffusion_models \
            --token "$HF_TOKEN" && \
        echo "[flux-fill-inpaint] All models downloaded successfully."
    fi
) &
MODEL_DL_PID=$!

# Start handler immediately so RunPod sees a healthy worker.
# The handler will wait for ComfyUI on the first inference request.
echo "[flux-fill-inpaint] Starting RunPod handler..."
exec python /worker/handler.py
