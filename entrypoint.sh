#!/bin/bash
echo "[flux-fill-inpaint] Container startup..."
echo "[flux-fill-inpaint] RUNPOD_WEBHOOK_GET_JOB=${RUNPOD_WEBHOOK_GET_JOB:-NOT SET}"

# Start ComfyUI (fast without models)
echo "[flux-fill-inpaint] Starting ComfyUI..."
python /ComfyUI/main.py --listen --disable-auto-launch &
COMFYUI_PID=$!

# Start handler immediately so RunPod sees a healthy worker.
# The handler will download any missing models on the first inference request.
echo "[flux-fill-inpaint] Starting RunPod handler..."
exec python /worker/handler.py
