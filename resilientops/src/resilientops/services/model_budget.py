"""Shared process-level pacing for ADK, extraction and chat model requests."""

import threading
import time

_lock = threading.Lock()
_next_slot = 0.0


def wait_for_model_slot(requests_per_minute: int):
    global _next_slot
    if requests_per_minute <= 0:
        return
    with _lock:
        now = time.monotonic()
        slot = max(now, _next_slot)
        _next_slot = slot + 60 / requests_per_minute
    if slot > now:
        time.sleep(slot - now)
