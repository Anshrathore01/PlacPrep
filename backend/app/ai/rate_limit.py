import threading
import time
import logging
import math
from collections import defaultdict, deque

from fastapi import HTTPException

_lock = threading.Lock()
logger = logging.getLogger(__name__)
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
            retry_after = max(1, math.ceil(window - (now - events[0])))
            logger.warning(
                "AI application rate limit feature=%s retry_after_seconds=%s",
                feature,
                retry_after,
            )
            raise HTTPException(
                status_code=429,
                detail="Too many AI requests. Please retry after the indicated delay.",
                headers={"Retry-After": str(retry_after)},
            )
        events.append(now)
