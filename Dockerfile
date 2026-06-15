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
    && pip install runpod websocket-client

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

# Download FLUX.1 Fill [dev] model
# Note: this is a gated model on Hugging Face. You must accept the license at
# https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev before the download
# will succeed. If your RunPod environment has HF_TOKEN set, the file is
# fetched with authentication automatically.
ARG HF_TOKEN=""
ENV HF_TOKEN=${HF_TOKEN}
RUN if [ -n "$HF_TOKEN" ]; then \
        huggingface-cli download black-forest-labs/FLUX.1-Fill-dev \
            flux1-fill-dev.safetensors \
            --local-dir /ComfyUI/models/diffusion_models \
            --token "$HF_TOKEN" || true; \
    fi

# Public FLUX text encoders + VAE (no gating required)
RUN wget -q --show-progress \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors" \
        -O /ComfyUI/models/text_encoders/t5xxl_fp16.safetensors \
    && wget -q --show-progress \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
        -O /ComfyUI/models/text_encoders/clip_l.safetensors \
    && wget -q --show-progress \
        "https://huggingface.co/Comfy-Org/Lumina_Image_2.0_Repackaged/resolve/main/split_files/vae/ae.safetensors" \
        -O /ComfyUI/models/vae/ae.safetensors

# Fallback: if flux1-fill-dev.safetensors wasn't fetched above (no HF_TOKEN),
# try a public mirror. Comment out the next block if you only want to use a
# Network Volume for the gated model.
RUN if [ ! -s /ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors ]; then \
        echo "[flux-fill-inpaint] flux1-fill-dev.safetensors missing."; \
        echo "[flux-fill-inpaint] Either:"; \
        echo "  1) build with --build-arg HF_TOKEN=hf_xxx (you must have accepted the license at"; \
        echo "     https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev )"; \
        echo "  2) mount a RunPod Network Volume that already contains the file at"; \
        echo "     /runpod-volume/ComfyUI/models/diffusion_models/flux1-fill-dev.safetensors"; \
    fi

# Copy worker source
COPY . /worker
RUN mv /worker/inpaint_api.json /inpaint_api.json \
    && chmod +x /worker/entrypoint.sh

WORKDIR /

CMD ["/bin/bash", "/worker/entrypoint.sh"]
