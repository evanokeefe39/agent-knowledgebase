"""Runtime driver: build the Voyage index under free-tier limits (3 RPM / 10K TPM).

Does not modify kb/dense.py — only lowers VoyageProvider.batch_size at runtime so
each request fits the token-per-minute cap, then calls the idempotent build().
"""
import sys
import time

from kb import dense

dense.VoyageProvider.batch_size = 4

start = time.time()
while True:
    stored = dense.build(provider_name="voyage")
    if stored == 0:
        break
    if time.time() - start > 3600:
        print("driver: time budget exhausted; rerun to continue", file=sys.stderr)
        sys.exit(1)
    time.sleep(25)  # stay under 3 RPM across build() iterations
print("driver: voyage index build complete")
