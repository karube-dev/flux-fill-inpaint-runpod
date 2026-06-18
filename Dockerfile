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
RUN pip install --upgrade pip \
    && pip install -U "huggingface_hub[hf_transfer]" \
    && pip install runpod websocket-client Pillow

# ComfyUI
RUN git clone https://github.com/comfyanonymous/ComfyUI.git /ComfyUI \
    && cd /ComfyUI \
    && pip install -r requirements.txt

# ComfyUI-Manager
RUN git clone https://github.com/Comfy-Org/ComfyUI-Manager.git /ComfyUI/custom_nodes/ComfyUI-Manager \
    && cd /ComfyUI/custom_nodes/ComfyUI-Manager \
    && pip install -r requirements.txt

# Prepare model directories
RUN mkdir -p /ComfyUI/models/diffusion_models \
             /ComfyUI/models/text_encoders \
             /ComfyUI/models/vae \
             /ComfyUI/models/clip_vision

# Pre-download the public (non-gated) FLUX assets at build time.
# These are not gated on Hugging Face and are safe to bake into the image.
RUN wget -q --show-progress \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" \
        -O /ComfyUI/models/text_encoders/t5xxl_fp16.safetensors \
    && wget -q --show-progress \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
        -O /ComfyUI/models/text_encoders/clip_l.safetensors \
    && wget -q --show-progress \
        "https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" \
        -O /ComfyUI/models/vae/ae.safetensors

# The gated FLUX.1 Fill [dev] model is downloaded at container startup
# (see /worker/entrypoint.sh) using the HF_TOKEN environment variable.
# Set HF_TOKEN as a RunPod Environment Variable before deploying.

# Copy worker source
COPY . /worker
RUN mv /worker/inpaint_api.json /inpaint_api.json \
    && chmod +x /worker/entrypoint.sh

WORKDIR /

CMD ["/worker/entrypoint.sh"]
