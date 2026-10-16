"""Detached metadata loaders: closing a window never destroys a running QThread."""

from threading import Event
from aqt.qt import QThread, QApplication, pyqtSignal
from ..utils.media import profile_token
from ..utils.logger import logger

_ACTIVE_LOADERS = set()


class ServiceLoaderThread(QThread):
    finished_signal = pyqtSignal(dict)
    failed = pyqtSignal(str)
    progress = pyqtSignal(int, int)

    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.cancelled = Event()
        self.token = profile_token()
        self.finished.connect(self._release)

    def start(self):
        _ACTIVE_LOADERS.add(self)
        super().start()

    def stop(self):
        self.cancelled.set()
        self.requestInterruption()

    def stopped(self):
        return self.cancelled.is_set() or self.token != profile_token()

    def run(self):
        try:
            services = self.controller.load_services(cancelled=self.stopped, progress=self.progress.emit)
            if not self.stopped():
                self.finished_signal.emit(services)
        except Exception as error:
            if not self.stopped():
                logger.exception('Could not load content sources')
                self.failed.emit(type(error).__name__)

    def _release(self):
        _ACTIVE_LOADERS.discard(self)
        self.deleteLater()


def cancel_loaders(wait=False):
    for loader in list(_ACTIVE_LOADERS):
        loader.stop()
    if wait:
        while _ACTIVE_LOADERS:
            for loader in list(_ACTIVE_LOADERS):
                loader.wait(30)
            QApplication.processEvents()
