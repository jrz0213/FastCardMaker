"""Global AI sending controls displayed below the field table."""
from aqt.qt import *
from ..translations import text as tr


class ConfigurationAI(QPushButton):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.mode = QComboBox(self)
        self.mode.addItem(tr('每张卡片一次发送（默认）'), 'note')
        self.mode.addItem(tr('每个字段分别发送'), 'field')
        self.mode.hide()
        self.loading = False
        self.mode.currentIndexChanged.connect(self.edit)
        self.mode.currentIndexChanged.connect(self.update_hint)
        self.clicked.connect(self.toggle_mode)
        self.update_hint()

    def update_hint(self, *_):
        combined = self.mode.currentData() == 'note'
        self.setText(tr('AI：按卡片合并') if combined else tr('AI：逐字段发送'))
        self.setChecked(combined)
        self.setToolTip(tr('点击切换，全局生效。') + '\n' +
                          (tr('所有笔记类型和配置共用；同一卡片中使用同一 AI 连接的字段合并请求，返回后自动拆分。')
                          if self.mode.currentData() == 'note' else
                          tr('所有配置共用；每个 AI 目标字段单独发送，Skill 仍使用对应 AI 配置的设置。')))

    def toggle_mode(self, *_):
        self.mode.setCurrentIndex(1 if self.mode.currentData() == 'note' else 0)

    def load(self, mode):
        self.loading = True
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        self.loading = False

    def edit(self, *_):
        if not self.loading:
            self.changed.emit()
