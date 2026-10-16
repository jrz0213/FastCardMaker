"""Independent progress lanes; asynchronous queries never block other windows."""

from aqt.qt import *
from ..translations import text as tr


class QueryProgressWindow(QDialog):
    background_requested = pyqtSignal()

    def __init__(self, dictionary_total, ai_total, rate, parent=None, show_window=True):
        if not isinstance(parent, QWidget):
            parent = QApplication.activeWindow()
        super().__init__(parent)
        self.setWindowTitle('FastCM - ' + tr('词典与 AI 查询'))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.setMinimumWidth(440)
        layout = QVBoxLayout(self)
        self.dictionary = ProgressLane(self, tr('词典查询'), dictionary_total)
        self.ai = ProgressLane(self, tr('AI 查询'), ai_total, rate)
        for lane in (self.dictionary, self.ai):
            layout.addWidget(lane.group)
        self.dictionary.group.setVisible(dictionary_total > 0)
        self.ai.group.setVisible(ai_total > 0)
        self.write_status = QLabel(tr('正在核对编辑器并保存结果…'))
        self.write_status.setWordWrap(True)
        self.write_status.hide()
        layout.addWidget(self.write_status)
        self.background_button = QPushButton(tr('后台运行'))
        self.background_button.clicked.connect(self.run_in_background)
        self.minimize_button = QPushButton(tr('最小化'))
        self.minimize_button.setToolTip(tr('收起查询窗口和配置页进度，任务继续，可从 FastCM 菜单查看。'))
        self.minimize_button.clicked.connect(self.run_in_background)
        background_actions = QHBoxLayout()
        background_actions.addWidget(self.background_button)
        background_actions.addWidget(self.minimize_button)
        layout.addLayout(background_actions)
        cancel = QPushButton(tr('全部取消'))
        cancel.clicked.connect(self.cancel_all)
        layout.addWidget(cancel)
        if show_window:
            self.show()

    def cancel_all(self):
        self.dictionary.cancel()
        self.ai.cancel()

    def closeEvent(self, event):
        self.run_in_background()
        event.ignore()

    def reject(self):
        self.run_in_background()

    def run_in_background(self):
        self.hide()
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.background_requested.emit()

    def finish(self):
        self.hide()
        self.deleteLater()


class ProgressLane:
    def __init__(self, parent, title, total, rate=None):
        self.group = QGroupBox(title, parent)
        layout = QVBoxLayout(self.group)
        self.label = QLabel()
        self.label.setWordWrap(True)
        self.bar = QProgressBar()
        self.bar.setRange(0, max(1, total))
        self.button = QPushButton(tr('取消'))
        self.button.clicked.connect(self.cancel)
        for widget in (self.label, self.bar, self.button):
            layout.addWidget(widget)
        self.total, self.rate = total, rate
        self.cancelled = False
        self.done = False
        self.update(0, 0)

    def start(self, **kwargs):
        self.total = kwargs.get('max', self.total)

    def cancel(self):
        if not self.done:
            self.cancelled = True
            self.button.setEnabled(False)
            self.label.setText(tr('正在取消，等待已发出的请求结束…'))

    def abort(self):
        return self.cancelled

    def update(self, completed, failed):
        self.bar.setValue(completed)
        if self.cancelled:
            return
        message = tr('完成：%s / %s · 失败：%s') % (completed, self.total, failed)
        if self.rate is not None:
            message += tr(' · 平滑发送：%s 次/分钟') % self.rate
        if self.done:
            message += tr(' · 已完成')
        self.label.setText(message)

    def update_labels(self, data):
        completed = data.get('words_number', 0) + data.get('skips_number', 0) + data.get('fails_number', 0)
        self.update(completed, data.get('fails_number', 0))

    def finish(self):
        if self.done:
            return
        self.done = True
        self.button.setEnabled(False)
        self.label.setText(self.label.text() + tr(' · 已取消' if self.cancelled else ' · 已完成'))

    def update_title(self, title):
        pass
