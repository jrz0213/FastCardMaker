"""Non-modal scheduled-run countdown; closing skips this tick."""
import math
import time
from aqt.qt import *
from ..translations import text as tr


class AutomaticPrompt(QDialog):
    def __init__(self, parent, start):
        super().__init__(parent, Qt.WindowType.Tool | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle(tr('自动运行'))
        self.setModal(False)
        self.start_callback = start
        self.deadline = time.monotonic() + 10
        self.finished_once = False
        layout = QVBoxLayout(self)
        self.label = QLabel()
        layout.addWidget(self.label)
        buttons = QHBoxLayout()
        run = QPushButton(tr('立即运行'))
        skip = QPushButton(tr('跳过本次'))
        run.clicked.connect(self.launch)
        skip.clicked.connect(self.reject)
        buttons.addWidget(run)
        buttons.addWidget(skip)
        layout.addLayout(buttons)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_countdown)
        self.timer.start(200)
        self.update_countdown()
        self.adjustSize()
        area = parent.frameGeometry() if parent else self.screen().availableGeometry()
        self.move(area.center().x() - self.width() // 2, area.top() + 35)

    def update_countdown(self):
        remaining = max(0, math.ceil(self.deadline - time.monotonic()))
        self.label.setText(tr('将在 %s 秒后自动查询新增笔记。') % remaining)
        if remaining == 0:
            self.launch()

    def launch(self):
        if self.finished_once:
            return
        self.finished_once = True
        self.timer.stop()
        self.accept()
        self.start_callback()

    def done(self, result):
        self.finished_once = True
        self.timer.stop()
        super().done(result)
