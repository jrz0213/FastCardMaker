"""Shared smooth send pacing; permits cannot accumulate into a burst."""

from threading import Condition
from time import monotonic

from .config import ai_send_rate, MAX_IN_FLIGHT


class AIRequestLimiter:
    def __init__(self, clock=monotonic, rate=None, max_active=MAX_IN_FLIGHT):
        self._condition = Condition()
        self._clock = clock
        self._rate = rate or ai_send_rate
        self._last_sent = None
        self._active = 0
        self._max_active = max_active
        self._blocked_until = 0

    def acquire(self, blocking=True, timeout=None, cancelled=None):
        deadline = None if timeout is None else self._clock() + timeout
        with self._condition:
            while True:
                if cancelled and cancelled():
                    return False
                now = self._clock()
                interval = 60.0 / self._rate()
                delay = max(0, self._blocked_until - now,
                            0 if self._last_sent is None else self._last_sent + interval - now)
                if delay <= 0 and self._active < self._max_active:
                    self._last_sent = now
                    self._active += 1
                    return True
                if not blocking:
                    return False
                remaining = None if deadline is None else deadline - now
                if remaining is not None and remaining <= 0:
                    return False
                wait = min(delay if delay > 0 else 0.1, 0.1)
                self._condition.wait(min(wait, remaining) if remaining is not None else wait)

    def release(self):
        """Finishing a response does not reset or refund its send interval."""
        with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    def defer(self, seconds):
        with self._condition:
            self._blocked_until = max(self._blocked_until, self._clock() + seconds)
            self._condition.notify_all()
