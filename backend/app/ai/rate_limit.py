import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException

_lock = threading.Lock()
_events: dict[tuple[str, int], deque[float]] = defaultdict(deque)
_LIMITS = {"mock": (8, 60.0), "placo": (30, 60.0)}


def enforce_user_limit(feature: str, user_id: int) -> None:
    limit, window = _LIMITS[feature]
    now = time.monotonic()
    with _lock:
        events = _events[(feature, user_id)]
        while events and now - events[0] >= window:
            events.popleft()
        if len(events) >= limit:
            raise HTTPException(
                status_code=429,
                detail="Too many AI requests. Please try again shortly.",
            )
        events.append(now)
