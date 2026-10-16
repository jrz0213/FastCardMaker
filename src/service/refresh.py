"""Background registry scans with atomic, main-thread publication."""

from copy import deepcopy
from types import SimpleNamespace

from aqt.qt import QObject, QThread, QApplication, pyqtSignal

from ..context import config
from ..utils.media import profile_token
from ..utils.logger import logger


def scan_registry(settings, cancelled):
    import os
    scan_settings = SimpleNamespace(dirs=list(settings.dirs), dicts=deepcopy(settings.dicts))
    enabled = set()
    if settings.folder_sync:
        from .custom_scripts import sync_folder_scripts
        enabled = sync_folder_scripts(settings.dirs, os.path.join(os.path.dirname(__file__), 'dict'), cancelled)
        for unique in enabled:
            scan_settings.dicts.setdefault(unique, {})['enabled'] = False
    from .manager import ServiceManager
    prepared = ServiceManager(settings=scan_settings, cancelled=cancelled)
    prepared.enabled_scripts = enabled
    return prepared


class RegistryScan(QThread):
    ready = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, request, token, settings):
        super().__init__()
        self.request, self.token, self.settings = request, token, settings

    def cancelled(self):
        return self.isInterruptionRequested() or self.token != profile_token()

    def run(self):
        try:
            prepared = scan_registry(self.settings, self.cancelled)
            if not self.cancelled():
                self.ready.emit(prepared)
        except Exception as error:
            if not self.cancelled():
                logger.exception('Dictionary refresh failed')
                self.failed.emit(type(error).__name__)


class RegistryUpdater(QObject):
    updated = pyqtSignal()
    failed = pyqtSignal(str)
    started = pyqtSignal()
    idle = pyqtSignal()

    def __init__(self, manager, pool):
        super().__init__()
        self.manager, self.pool = manager, pool
        self._thread = None
        self._pending = None
        self._request = 0

    @property
    def busy(self):
        return self._thread is not None or self._pending is not None

    def request(self, folder_sync=False):
        folder_sync = (folder_sync or (self._pending is not None and self._pending[2].folder_sync)
                       or (self._thread is not None and self._thread.settings.folder_sync))
        self._request += 1
        self._pending = (self._request, profile_token(),
                         SimpleNamespace(dirs=list(config.dirs), dicts=deepcopy(config.dicts), folder_sync=folder_sync))
        self.started.emit()
        if self._thread is None:
            self._launch()
        else:
            self._thread.requestInterruption()

    def _launch(self):
        request, token, settings = self._pending
        self._pending = None
        thread = self._thread = RegistryScan(request, token, settings)
        thread.ready.connect(self._publish)
        thread.failed.connect(self._failed)
        thread.finished.connect(self._finished)
        thread.start()

    def _publish(self, prepared):
        thread = self.sender()
        if thread.request == self._request and thread.token == profile_token():
            if getattr(prepared, 'enabled_scripts', None):
                dicts = deepcopy(config.dicts)
                for unique in prepared.enabled_scripts:
                    # A later explicit enable/disable choice takes precedence.
                    if unique not in dicts:
                        dicts[unique] = {'enabled': False}
                config.update({'dicts': dicts})
            self.manager.adopt(prepared)
            self.pool.clean()
            self.updated.emit()

    def _failed(self, error):
        thread = self.sender()
        if thread.request == self._request and thread.token == profile_token():
            self.failed.emit(error)

    def _finished(self):
        thread = self.sender()
        if self._thread is thread:
            self._thread = None
        thread.deleteLater()
        if self._pending is not None:
            if self._pending[1] == profile_token():
                self._launch()
            else:
                self._pending = None
        if not self.busy:
            self.idle.emit()

    def cancel(self, wait=False):
        self._request += 1
        self._pending = None
        if self._thread is not None:
            self._thread.requestInterruption()
        if wait:
            while self._thread is not None:
                self._thread.wait(30)
                QApplication.processEvents()


_updater = None


def get_updater():
    global _updater
    if _updater is None:
        from . import service_manager, service_pool
        _updater = RegistryUpdater(service_manager, service_pool)
    return _updater
