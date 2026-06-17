"""
Ultra-minimal RunPod serverless worker — no ComfyUI, no models, no dependencies beyond runpod.
Purpose: verify that runpod.serverless.start() works and worker becomes healthy.
"""
import runpod

def handler(job):
    return {
        "status": "ok",
        "echo": job.get("input", {}),
        "message": "minimal handler works!"
    }

if __name__ == "__main__":
    runpod.serverless.start({"handler": handler})
