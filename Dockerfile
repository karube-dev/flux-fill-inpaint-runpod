FROM runpod/pytorch:2.4.0-py3.11-cuda12.4.1-devel-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV HF_HUB_ENABLE_HF_TRANSFER=0

WORKDIR /

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
        git wget curl ca-certificates libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Python deps
RUN pip install --upgrade pip --no-cache-dir \
    && pip install --no-cache-dir \
        "huggingface_hub[hf_transfer]" \
        runpod \
        websocket-client \
        Pillow

# ComfyUI
RUN git clone --depth 1 https://github.com/comfyanonymous/ComfyUI.git /ComfyUI \
    && cd /ComfyUI \
    && pip install --no-cache-dir -r requirements.txt

# ComfyUI-Manager
RUN git clone --depth 1 https://github.com/Comfy-Org/ComfyUI-Manager.git /ComfyUI/custom_nodes/ComfyUI-Manager \
    && cd /ComfyUI/custom_nodes/ComfyUI-Manager \
    && pip install --no-cache-dir -r requirements.txt

# Prepare model directories
RUN mkdir -p /ComfyUI/models/diffusion_models \
             /ComfyUI/models/text_encoders \
             /ComfyUI/models/vae \
             /ComfyUI/models/clip_vision

# All models (t5xxl, clip_l, vae, flux1-fill-dev) are downloaded at
# container startup by /worker/entrypoint.sh using HF_TOKEN.
# This keeps the image small for fast pulls.

# Copy worker source
COPY . /worker
RUN mv /worker/inpaint_api.json /inpaint_api.json \
    && chmod +x /worker/entrypoint.sh

WORKDIR /

CMD ["/bin/bash", "/worker/entrypoint.sh"]
