#!/bin/bash
set -e

echo "[flux-fill-inpaint] Starting ComfyUI in the background..."

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
