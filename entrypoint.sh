#!/bin/bash
echo "[flux-fill-inpaint] Container startup..."
echo "[flux-fill-inpaint] RUNPOD_WEBHOOK_GET_JOB=${RUNPOD_WEBHOOK_GET_JOB:-NOT SET}"

# Start ComfyUI (fast without models)
echo "[flux-fill-inpaint] Starting ComfyUI..."
python /ComfyUI/main.py --listen --disable-auto-launch &
COMFYUI_PID=$!

# Download models in the background
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

# Start handler immediately so RunPod sees a healthy worker.
# The handler will wait for ComfyUI on the first inference request.
echo "[flux-fill-inpaint] Starting RunPod handler..."
exec python /worker/handler.py
