"""Bounded service leases with cancellable waits and safe pool invalidation."""

from contextlib import contextmanager
from queue import Queue, Empty
from threading import Condition
from time import monotonic

from ..utils.logger import logger


class ServicePool:
    MAX_INSTANCES = 5

    def __init__(self, manager):
        self.manager = manager
        self.pools = {}
        self.instance_counts = {}
        self._condition = Condition()
        self._generation = 0
        self._borrowed = {}

    def get(self, unique, cancelled=None, timeout=30):
        enabled = getattr(self.manager, 'is_enabled', None)
        if callable(enabled) and not enabled(unique):
            return None
        deadline = None if timeout is None else monotonic() + timeout
        with self._condition:
            generation = self._generation
            while True:
                if generation != self._generation or (cancelled and cancelled()):
                    return None
                queue = self.pools.setdefault(unique, Queue())
                self.instance_counts.setdefault(unique, 0)
                try:
                    service = queue.get_nowait()
                    self._borrowed[id(service)] = (unique, generation)
                    return service
                except Empty:
                    pass
                if self.instance_counts[unique] < self.MAX_INSTANCES:
                    self.instance_counts[unique] += 1
                    break
                remaining = None if deadline is None else deadline - monotonic()
                if remaining is not None and remaining <= 0:
                    return None
                self._condition.wait(0.05 if remaining is None else min(0.05, remaining))
        service = None
        try:
            service = self.manager.get_service(unique)
        finally:
            with self._condition:
                current = generation == self._generation
                if current and service is None:
                    self.instance_counts[unique] -= 1
                if current and service is not None:
                    self._borrowed[id(service)] = (unique, generation)
                self._condition.notify_all()
        if not current:
            self._close(service)
            return None
        if cancelled and cancelled():
            self.put(service)
            return None
        return service

    @contextmanager
    def borrow(self, unique, **kwargs):
        service = self.get(unique, **kwargs)
        try:
            yield service
        finally:
            self.put(service)

    def put(self, service):
        if service is None:
            return
        with self._condition:
            lease = self._borrowed.pop(id(service), None)
            if lease is None:
                return
            unique, generation = lease
            current = generation == self._generation
            if current:
                self.pools[unique].put(service)
            self._condition.notify_all()
        if not current:
            self._close(service)

    @staticmethod
    def _close(service):
        session = getattr(service, 'session', None)
        if session is not None:
            try:
                session.close()
            except Exception:
                logger.exception('Could not close dictionary HTTP session')

    def clean(self):
        idle = []
        with self._condition:
            for queue in self.pools.values():
                while True:
                    try:
                        idle.append(queue.get_nowait())
                    except Empty:
                        break
            self._generation += 1
            self.pools = {}
            self.instance_counts = {}
            self._condition.notify_all()
        for service in idle:
            self._close(service)
