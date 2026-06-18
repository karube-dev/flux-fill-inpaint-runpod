"""
Diagnostic handler: print all env vars, try runpod.serverless.start(), catch errors.
"""
import os, sys, json, traceback

print("=" * 80)
print("DIAGNOSTIC START")
print("=" * 80)

# Print all RUNPOD_* env vars
print("\n[1] RUNPOD Environment Variables:")
runpod_vars = {k: v for k, v in os.environ.items() if 'RUNPOD' in k.upper()}
if runpod_vars:
    for k, v in sorted(runpod_vars.items()):
        # Mask sensitive values
        if 'KEY' in k or 'TOKEN' in k or 'SECRET' in k:
            v = v[:8] + '...' if len(v) > 8 else '***'
        print(f"  {k} = {v}")
else:
    print("  (none found)")

# Print other relevant env vars
print("\n[2] Other Environment Variables:")
for k in ['PATH', 'PYTHONPATH', 'HOME', 'PWD', 'USER']:
    if k in os.environ:
        print(f"  {k} = {os.environ[k]}")

# Check if runpod is installed
print("\n[3] RunPod Package:")
try:
    import runpod
    print(f"  Version: {runpod.__version__}")
    print(f"  Location: {runpod.__file__}")
except ImportError as e:
    print(f"  ERROR: {e}")
    print("  Exiting...")
    sys.exit(1)

# Try to call runpod.serverless.start()
print("\n[4] Attempting runpod.serverless.start():")
try:
    def dummy_handler(job):
        return {"status": "ok"}
    
    print("  Calling start()...")
    runpod.serverless.start({"handler": dummy_handler})
    print("  start() returned (should not happen in production)")
except Exception as e:
    print(f"  ERROR: {type(e).__name__}: {e}")
    print(f"  Traceback:")
    traceback.print_exc()

print("\n" + "=" * 80)
print("DIAGNOSTIC END")
print("=" * 80)

# Keep process alive
print("\nSleeping forever...")
import time
while True:
    time.sleep(60)
