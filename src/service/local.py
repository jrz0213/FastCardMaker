"""Local dictionary lifecycle, shared builders, and background build signals."""

import os
from hashlib import md5
from queue import Queue, Empty

from aqt import mw
from aqt.qt import QMutex, QThread, QObject, pyqtSignal

from ..utils.logger import logger
from .core import Service
from ..translations import text as tr


class DictionaryNotReady(ValueError):
    def __init__(self, status):
        self.status = status
        message = (tr("词典数据库正在建立中，请稍后再查。") if status in ("checking", "building")
                   else tr("词典初始化失败，请检查文件并重试。"))
        super().__init__(message)


class _DictSignal(QObject):
    status_changed = pyqtSignal(str, str)

if not hasattr(mw, 'dict_signals'):
    mw.dict_signals = _DictSignal()

class _DictBuilderQueueThread(QThread):
    def __init__(self, queue_ref, mdx_builders_ref, build_status_ref, mutex_ref):
        super().__init__()
        self._queue = queue_ref
        self._mdx_builders = mdx_builders_ref
        self._build_status = build_status_ref
        self._mutex = mutex_ref

    def run(self):
        while True:
            try:
                func, hash_key = self._queue.get(True, timeout=1.0)
            except Empty:
                continue
            except Exception:
                continue

            # 🌟 收到任务，更改状态为 building 并触发信号
            self._mutex.lock()
            self._build_status[hash_key] = "building"
            self._mutex.unlock()
            logger.info(f"后台线程开始建库解析 | 任务 Hash: [{hash_key}]")
            mw.dict_signals.status_changed.emit(hash_key, "building")

            try:
                builder = func()
            except Exception as e:
                logger.error(f"后台排队构建数据库失败: {str(e)}")
                builder = None
            finally:
                # Only a successfully initialized builder is ready.
                self._mutex.lock()
                self._mdx_builders[hash_key] = builder
                self._build_status[hash_key] = "ready" if builder is not None else "failed"
                self._mutex.unlock()
                logger.info(f"后台建库解析完成 | 任务 Hash: [{hash_key}]")
                mw.dict_signals.status_changed.emit(hash_key, "ready" if builder is not None else "failed")
                self._queue.task_done()

class LocalService(Service):
    def __init__(self):
        super(LocalService, self).__init__()
        self.dict_path = ""
        self.builder = None
        self.missed_css = set()

    _mdx_builders = {}
    _build_status = {}
    _build_factories = {}
    _build_queue = Queue()
    _builder_thread = None
    _mutex_builder = QMutex()

    @staticmethod
    def builder_key(path):
        path = str(path)
        if path.lower().endswith('.ifo'):
            path = path[:-4]
        path = os.path.normcase(os.path.abspath(path))
        return md5(path.encode('utf-8')).hexdigest()

    @staticmethod
    def _get_builder(key, func=None, retry=False):
        hash_key = LocalService.builder_key(key)
        checking = False
        LocalService._mutex_builder.lock()
        try:
            status = LocalService._build_status.get(hash_key, 'uninitialized')
            if func is not None:
                LocalService._build_factories[hash_key] = (key, func)
            if func is not None and (status == 'uninitialized' or (retry and status == 'failed')):
                LocalService._build_status[hash_key] = 'checking'
                checking = True
            builder = LocalService._mdx_builders.get(hash_key)
        finally:
            LocalService._mutex_builder.unlock()
        if checking:
            # Emit without the mutex: Qt can synchronously call UI slots that
            # read the status or enqueue another request.
            mw.dict_signals.status_changed.emit(hash_key, 'checking')
            LocalService._mutex_builder.lock()
            try:
                LocalService._build_queue.put((func, hash_key))
                if LocalService._builder_thread is None or not LocalService._builder_thread.isRunning():
                    LocalService._builder_thread = _DictBuilderQueueThread(
                        LocalService._build_queue, LocalService._mdx_builders,
                        LocalService._build_status, LocalService._mutex_builder)
                    LocalService._builder_thread.start()
            finally:
                LocalService._mutex_builder.unlock()
        return builder

    @classmethod
    def get_db_status(cls, dict_path):
        key = cls.builder_key(dict_path)
        cls._mutex_builder.lock()
        try:
            status = cls._build_status.get(key, 'uninitialized')
            if status in ('checking', 'building', 'failed'):
                return status
            return 'ready' if cls._mdx_builders.get(key) is not None else 'uninitialized'
        finally:
            cls._mutex_builder.unlock()

    @classmethod
    def retry_build(cls, dict_path):
        key = cls.builder_key(dict_path)
        cls._mutex_builder.lock()
        try:
            factory = cls._build_factories.get(key)
            failed = cls._build_status.get(key) == 'failed'
        finally:
            cls._mutex_builder.unlock()
        if not factory or not failed:
            return False
        cls._get_builder(*factory, retry=True)
        return True

    @classmethod
    def find_dictionary(cls, prefixes):
        """Resolve legacy auto-detection without borrowing nested pool leases."""
        from ..context import config
        for folder in config.dirs:
            for directory, _, files in os.walk(folder):
                for filename in files:
                    if not filename.lower().endswith('.mdx'):
                        continue
                    path = os.path.join(directory, filename)
                    builder = cls._get_builder(path)
                    title = getattr(builder, '_title', '') if builder is not None else ''
                    if any(title.lower().startswith(prefix.lower()) or filename.lower().startswith(prefix.lower())
                           for prefix in prefixes):
                        return path
        return ''

    @property
    def support(self):
        return os.path.isfile(self.dict_path)

    @property
    def title(self):
        return getattr(self, '__register_label__', u'Unkown')

    @property
    def _filename(self):
        return os.path.splitext(os.path.basename(self.dict_path))[0]
