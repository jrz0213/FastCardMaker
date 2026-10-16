"""Configuration-page progress and menu access, without main-window bars."""

from aqt.qt import *
import time
from ..translations import text as tr


class ProgressHub(QObject):
    started = pyqtSignal(object)
    completed = pyqtSignal(object)
    minimized = pyqtSignal(object)
    reset = pyqtSignal()
    current = None
    last = None

    def clear(self):
        if self.last and self.last.window:
            self.last.window.close()
        self.current = self.last = None
        self.reset.emit()
        for window in QApplication.topLevelWidgets():
            dock = getattr(window, '_fwq_progress_dock', None)
            if dock is not None:
                try:
                    window.removeDockWidget(dock)
                    dock.deleteLater()
                except RuntimeError:
                    pass
                window._fwq_progress_dock = None


class ProgressReport(QObject):
    changed = pyqtSignal()

    def __init__(self, job):
        super().__init__()
        self.job_id = id(job)
        for name in ('token', 'total', 'completed', 'failed', 'conflicts'):
            setattr(self, name, getattr(job, name))
        self.cancelled = job.cancelled or job.dictionary.cancelled or job.ai.was_cancelled
        self.is_background = getattr(job, 'is_background', False)
        self.done, self.writing, self.write_queue = True, False, ()
        self.elapsed_seconds = int(time.monotonic() - job.started_at)
        self.timings = getattr(job, 'timings', {})
        self.dictionary_fields, self.ai_fields = job.dictionary.fields, job.ai.updated_fields
        self.errors = list(job.dictionary.errors) + list(job.ai.errors) + list(job.ai.validation_errors) + list(job.notices)
        self.window = None

    def cancel(self):
        pass

    def show_progress(self):
        if self.window is None:
            self.window = QDialog()
            self.window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
            self.window.destroyed.connect(lambda: setattr(self, 'window', None))
            self.window.setWindowTitle('FastCM - ' + tr('任务结果'))
            self.window.setWindowModality(Qt.WindowModality.NonModal)
            self.window.resize(560, 300)
            layout = QVBoxLayout(self.window)
            text = QPlainTextEdit()
            text.setReadOnly(True)
            text.setPlainText(tr('更新进度：%s / %s · 失败：%s · 冲突跳过：%s') %
                              (self.completed, self.total, self.failed, self.conflicts) + '\n' +
                              tr('已写入：词典 %s 个字段 · AI %s 个字段') % (self.dictionary_fields, self.ai_fields) + '\n\n' +
                              ('\n'.join(self.errors) or tr('没有错误。')))
            if self.timings:
                text.appendPlainText('\n' + tr('耗时：查询 %s 秒 · 等待缓存 %s 秒 · 保存 %s 秒 · 清理缓存 %s 秒 · 刷新通知 %s 秒') %
                    tuple('%.2f' % self.timings.get(name, 0) for name in ('query', 'cache_wait', 'save', 'cleanup', 'refresh')))
            layout.addWidget(text)
            close = QPushButton(tr('关闭'))
            close.clicked.connect(self.window.close)
            layout.addWidget(close)
        self.window.show()
        self.window.raise_()


_hub = None


def progress_hub():
    global _hub
    if _hub is None:
        _hub = ProgressHub()
    return _hub


class TaskProgress(QWidget):
    def __init__(self, job, parent=None):
        super().__init__(parent)
        self.job = None
        self.dismissed = getattr(job, 'is_background', False)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        self.label = QLabel()
        self.label.setWordWrap(True)
        layout.addWidget(self.label)
        controls = QHBoxLayout()
        self.bar = QProgressBar()
        self.bar.setMinimumWidth(120)
        self.details = QPushButton(tr('查看进度'))
        self.cancel = QPushButton(tr('取消任务'))
        self.close_button = QPushButton(tr('最小化'))
        self.close_button.setToolTip(tr('收起查询窗口和配置页进度，任务继续，可从 FastCM 菜单查看。'))
        self.close_button.clicked.connect(self.minimize)
        for widget in (self.bar, self.details, self.cancel, self.close_button):
            controls.addWidget(widget)
        controls.setStretch(0, 1)
        layout.addLayout(controls)
        progress_hub().completed.connect(self.completed_report)
        progress_hub().minimized.connect(self.minimized)
        progress_hub().reset.connect(self.hide)
        self.bind(job)

    def minimized(self, job):
        if job is self.job or getattr(self.job, 'job_id', None) == id(job):
            self.dismiss()

    def minimize(self):
        self.dismiss()
        if self.job.done:
            self.job.is_background = True
            progress_hub().minimized.emit(self.job)
        else:
            self.job.window.run_in_background()

    def finish_or_cancel(self):
        if self.job.done:
            self.minimize()
        else:
            self.job.cancel()

    def dismiss(self):
        self.dismissed = True
        self.hide()
        ancestor = self.parentWidget()
        while ancestor is not None:
            if isinstance(ancestor, QDockWidget):
                ancestor.hide()
                break
            ancestor = ancestor.parentWidget()

    def bind(self, job):
        if self.job is not None:
            try:
                self.job.changed.disconnect(self.refresh)
            except (TypeError, RuntimeError):
                pass
            for button in (self.details, self.cancel):
                try:
                    button.clicked.disconnect()
                except (TypeError, RuntimeError):
                    pass
        self.job = job
        if job.done:
            self.timer.stop()
        else:
            self.timer.start()
        self.details.clicked.connect(job.show_progress)
        self.cancel.clicked.connect(self.finish_or_cancel)
        job.changed.connect(self.refresh)
        self.refresh()

    def completed_report(self, report):
        if report.job_id == id(self.job):
            self.bind(report)

    def refresh(self):
        job = self.job
        self.bar.setRange(0, max(1, job.total))
        self.bar.setValue(job.completed)
        phase = getattr(job, 'phase', 'query')
        if not job.done and phase in ('cache', 'cleanup'):
            self.bar.setRange(0, 0)
        elif not job.done and phase == 'save':
            self.bar.setRange(0, max(1, job.save_total))
            self.bar.setValue(job.save_completed)
        message = tr('更新进度：%s / %s · 失败：%s · 冲突跳过：%s') % (job.completed, job.total, job.failed, job.conflicts)
        if not job.done and phase == 'cache':
            message += tr(' · 等待缓存落盘：剩余 %s 条') % len(job.cache_pending)
        elif not job.done and phase == 'cleanup':
            message += tr(' · 正在清理缓存…')
        elif not job.done and phase == 'save':
            message += tr(' · 保存笔记：%s / %s') % (job.save_completed, job.save_total)
        elif job.writing or (not getattr(job, 'collecting', False) and job.write_queue):
            message += tr(' · 正在保存…')
        elif job.done:
            message += tr(' · 已取消' if job.cancelled else ' · 已完成')
        elif job.cancelled:
            message += tr(' · 正在取消…')
        else:
            message += tr(' · 运行中')
        elapsed = job.elapsed_seconds if job.done else int(time.monotonic() - job.started_at)
        message += tr(' · 用时 %s 秒') % elapsed
        if job.done:
            message += '\n' + tr('已写入：词典 %s 个字段 · AI %s 个字段') % (job.dictionary_fields, job.ai_fields)
        elif hasattr(job, 'dictionary') and hasattr(job, 'ai'):
            message += '\n' + tr('已写入：词典 %s 个字段 · AI %s 个字段') % (job.dictionary.fields, job.ai.updated_fields)
        self.label.setText(message)
        self.label.setMinimumHeight(max(
            self.label.fontMetrics().height() * (message.count('\n') + 1),
            self.label.heightForWidth(max(1, self.label.width()))))
        self.cancel.setText(tr('完成任务') if job.done else tr('取消任务'))
        self.cancel.setEnabled(job.done or not job.cancelled)
        self.details.setText(tr('查看结果') if job.done else tr('查看进度'))
        self.details.setEnabled(True)
        self.setVisible(not self.dismissed)


class TaskMenuAction(QAction):
    """Live status in the browser menu, including the last completed result."""
    def __init__(self, parent):
        super().__init__(parent)
        self.job = None
        hub = progress_hub()
        hub.started.connect(self.bind)
        hub.completed.connect(self.bind)
        hub.reset.connect(lambda: self.bind(None))
        self.triggered.connect(self.open_progress)
        self.bind(hub.current or hub.last)

    def bind(self, job):
        if self.job is not None:
            try:
                self.job.changed.disconnect(self.refresh)
            except (RuntimeError, TypeError):
                pass
        self.job = job
        if job is not None:
            job.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        from ..utils.media import profile_token
        job = self.job
        if job is None or job.token != profile_token():
            self.setText(tr('后台任务：暂无任务'))
            self.setEnabled(False)
            return
        state = tr('已取消') if job.cancelled else tr('已完成') if job.done else tr('运行中')
        self.setText(tr('后台任务：%s · %s / %s') % (state, job.completed, job.total))
        self.setEnabled(True)

    def open_progress(self):
        if self.job is not None:
            self.job.show_progress()
