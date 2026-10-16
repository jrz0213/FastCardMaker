#-*- coding:utf-8 -*-
#
# Copyright (C) 2018 sthoo <sth201807@gmail.com>
#
# Support: Report an issue at https://github.com/sth2018/FastWordQuery/issues
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version; http://www.gnu.org/copyleft/gpl.html.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.
import anki.notes
from aqt import mw
from aqt.qt import *
from anki.notes import Note

from ..context import config
from ..lang import _
from ..gui import ProgressWindow

from ..utils.logger import logger
from ..utils import MapDict, wrap_css
from queue import Queue, Empty
from .common import InvalidWordException, query_flds, update_note_fields
from ..utils.media import profile_token


__all__ = ['QueryWorkerManager']


class QueryThread(QThread):
    """
    Query Worker Thread
    """

    note_flush = pyqtSignal(Note)
    results_ready = pyqtSignal(object, object, int, object)

    def __init__(self, manager):
        super(QueryThread, self).__init__()
        self.index = 0
        self.exit = False
        self.finished = False
        self.manager = manager
        self.note_flush.connect(manager.handle_flush)
        self.results_ready.connect(manager.handle_result)

    def run(self):
        while True:
            if self.exit or not self.manager or not self.manager.is_current_profile():
                break
            try:
                note = self.manager.queue.get(True, timeout=0.1)
            except Empty:
                self.exit = True
                continue

            try:
                results, success_num, missed_css = query_flds(
                    note, self.manager.query_fields,
                    cancelled=lambda: self.exit or not self.manager or not self.manager.is_current_profile(),
                    include_ai=self.manager.include_ai, mappings=self.manager.query_mappings)
                if not self.exit and self.manager:
                    self.results_ready.emit(note, results, success_num, missed_css)
            except InvalidWordException:
                self.results_ready.emit(note, {}, -1, [])
                if self.manager.total == 1:
                    # 【修复】禁止在 QThread 后台线程中调用 GUI 弹窗（会引起 Qt6 闪退），改用日志记录
                    logger.warning("查询失败，存在无效单词或未找到。")
            except Exception as error:
                # Unexpected dictionary errors must not strand the progress loop.
                self.results_ready.emit(note, {}, 0, [])
                logger.error('Dictionary query failed: %s', type(error).__name__)

            if self.manager:
                self.manager.queue.task_done()

        self.finished = True


class QueryWorkerManager(object):
    """
    Query Worker Thread Manager
    """

    def __init__(self):
        self._profile_token = profile_token()
        self.workers = []
        self.queue = Queue()
        self.mutex = QMutex()
        self.progress = ProgressWindow(mw)
        self.total = 0
        self.counter = 0
        self.fails = 0
        self.fields = 0
        self.skips = 0
        self.missed_css = list()
        self.errors = []
        self.flush = True
        self.query_fields = None
        self.query_mappings = None
        self.query_settings = None
        self.writer = None
        self.background_single = True
        self.include_ai = True
        self.cancelled = False

    def get_worker(self):
        worker = QueryThread(self)
        worker.index = len(self.workers) + 1
        self.workers.append(worker)
        return worker

    def start(self):
        self.total = self.queue.qsize()
        self.progress.start(max=self.total, min=0)
        self.update_progress()
        if self.total > 1:
            for _ in range(0, min(config.thread_number, self.total)):
                self.get_worker()

            for worker in self.workers:
                worker.start()
        else:
            worker = self.get_worker()
            if self.background_single:
                worker.start()
            else:
                worker.run()
                self.update_progress()

    def update(self, note, results, success_num, missed_css):
        self.mutex.lock()
        try:
            val = update_note_fields(note, results, self.query_settings)
            if success_num > 0 and val > 0:
                self.counter += 1
            elif success_num == 0:
                self.fails += 1
            else:
                self.skips += 1
            self.fields += val
            self.missed_css += missed_css
            self.errors.extend(getattr(results, 'errors', []))
        finally:
            self.mutex.unlock()
        if self.total > 1 or self.background_single:
            return val > 0
        self.handle_flush(note)
        return False

    def handle_result(self, note, results, success_num, missed_css):
        if self.cancelled or self.progress.abort() or not self.is_current_profile():
            return
        original = list(note.fields)
        counter, fields, skips, fails = self.counter, self.fields, self.skips, self.fails
        try:
            if self.update(note, results, success_num, missed_css):
                self.handle_flush(note)
        except Exception as error:
            note.fields[:] = original
            self.counter, self.fields, self.skips = counter, fields, skips
            self.fails = fails + 1
            logger.error('Dictionary result save failed: %s', type(error).__name__)

    def poll(self):
        if self.progress.abort() or not self.is_current_profile():
            self.cancelled = True
            for worker in self.workers:
                worker.exit = True
        else:
            self.update_progress()
        if self.workers and all(worker.finished for worker in self.workers):
            self.progress.finish()

    def is_current_profile(self):
        return self._profile_token == profile_token()

    def update_progress(self):
        self.progress.update_labels(MapDict(
            type='count',
            words_number=self.counter,
            skips_number=self.skips,
            fails_number=self.fails,
            fields_number=self.fields
        ))
        mw.app.processEvents()

    def join(self):
        for worker in self.workers:
            while not worker.finished:
                if self.progress.abort() or not self.is_current_profile():
                    self.cancelled = True
                    for pending in self.workers:
                        pending.exit = True
                    # Keep processing signals until in-flight requests finish;
                    # QThread objects must not be destroyed while still running.
                else:
                    self.update_progress()
                mw.app.processEvents()
                worker.wait(30)
        mw.app.processEvents()
        self.progress.finish()
    
    def handle_flush(self, note: anki.notes.Note):
        if self.flush and note:
            if self.writer:
                self.writer(note)
                return
            try:
                # flush is deprecated
                note.flush()
            except Exception:
                note.col.update_note(note)
