#!/bin/bash
echo "[flux-fill-inpaint] Container startup..."
echo "[flux-fill-inpaint] RUNPOD_WEBHOOK_GET_JOB=${RUNPOD_WEBHOOK_GET_JOB:-NOT SET}"

# Start ComfyUI (fast without models)
echo "[flux-fill-inpaint] Starting ComfyUI..."
python /ComfyUI/main.py --listen --disable-auto-launch &
COMFYUI_PID=$!

# Text encoders are baked into the Docker image.
# Download gated models (VAE + FLUX.1 Fill) at runtime using HF_TOKEN.
(
    if [ -n "$HF_TOKEN" ]; then
        # VAE (~350 MB)
        VAE_PATH="/ComfyUI/models/vae/ae.safetensors"
        if [ ! -s "$VAE_PATH" ]; then
            echo "[flux-fill-inpaint] Background: downloading FLUX VAE..."
            huggingface-cli download black-forest-labs/FLUX.1-dev \
                ae.safetensors \
                --local-dir /ComfyUI/models/vae \
                --token "$HF_TOKEN" && \
            echo "[flux-fill-inpaint] VAE downloaded."
        fi

        # FLUX.1 Fill [dev] (~23 GB)
        MODEL_PATH="/ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors"
        if [ ! -s "$MODEL_PATH" ]; then
            echo "[flux-fill-inpaint] Background: downloading FLUX.1 Fill [dev] (~23 GB)..."
            huggingface-cli download black-forest-labs/FLUX.1-Fill-dev \
                flux1-fill-dev.safetensors \
                --local-dir /ComfyUI/models/diffusion_models \
                --token "$HF_TOKEN" && \
            echo "[flux-fill-inpaint] FLUX.1 Fill model downloaded."
        fi
    else
        echo "[flux-fill-inpaint] WARNING: HF_TOKEN not set, cannot download gated models."
    fi
) &
MODEL_DL_PID=$!

# Start handler immediately so RunPod sees a healthy worker.
# The handler will wait for ComfyUI on the first inference request.
echo "[flux-fill-inpaint] Starting RunPod handler..."
exec python /worker/handler.py
