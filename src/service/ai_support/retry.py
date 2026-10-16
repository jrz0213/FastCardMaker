"""Bounded retries for explicit transient HTTP failures, never ambiguous timeouts."""

import math
import time
from datetime import timezone
from email.utils import parsedate_to_datetime


def retry_delay(response, attempt, retries=2):
    if attempt >= retries or response.status_code not in (408, 429, 500, 502, 503, 504):
        return None
    delay = 2.0 * (2 ** attempt)
    header = getattr(response, 'headers', {}).get('Retry-After')
    if isinstance(header, str):
        try:
            seconds = float(header)
        except ValueError:
            try:
                date = parsedate_to_datetime(header)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                seconds = date.timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                seconds = 0
        if math.isfinite(seconds):
            delay = max(delay, seconds)
    # Long server-mandated waits are left to the user rather than auto-retried early.
    return delay if delay <= 60 else None
