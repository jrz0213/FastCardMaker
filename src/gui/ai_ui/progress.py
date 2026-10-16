"""A dedicated, cancellable progress window for AI field requests."""

from ...translations import text as tr

from aqt.qt import *


class AIProgressWindow:
    def __init__(self, total, rate, parent=None):
        if not isinstance(parent, QWidget):
            parent = QApplication.activeWindow()
        self.window = QProgressDialog('', tr('取消 AI 查询'), 0, total, parent)
        self.window.setWindowTitle(tr('FastCM - AI 查询'))
        self.window.setWindowModality(Qt.WindowModality.ApplicationModal)
        self.window.setAutoClose(False)
        self.window.setAutoReset(False)
        self.window.setMinimumDuration(0)
        self.total = total
        self.rate = rate
        self.cancelled = False
        self.window.canceled.connect(self.cancel)
        self.update(0, 0)
        self.window.show()

    def cancel(self):
        self.cancelled = True

    def abort(self):
        return self.cancelled

    def update(self, completed, failed):
        self.window.setValue(completed)
        label = tr('AI 查询：%s / %s 项\n失败：%s 项 · 平滑发送：%s 次/分钟') % (
            completed, self.total, failed, self.rate)
        if self.cancelled:
            label += tr('\n正在取消：等待已发出的请求结束，未发送的任务已停止。')
            self.window.setCancelButton(None)
            self.window.show()
        self.window.setLabelText(label)

    def finish(self):
        self.window.hide()
        self.window.deleteLater()
