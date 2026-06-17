"""
Test: keep process alive without calling runpod.serverless.start().
If worker becomes healthy, RunPod manages handler registration externally.
"""
import time, os, json

print(f"PID={os.getpid()} RUNPOD_WEBHOOK_GET_JOB={os.environ.get('RUNPOD_WEBHOOK_GET_JOB','NOT SET')}")
print(f"All env: {json.dumps({k:v for k,v in os.environ.items() if 'RUNPOD' in k}, indent=2)}")
print("Sleeping forever...")
while True:
    time.sleep(60)
