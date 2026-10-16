"""Editable model name with optional provider-specific reference choices."""

from aqt.qt import QComboBox, QSignalBlocker

from ..service.ai_models import MODEL_SUGGESTIONS, MODEL_CATALOG_DATE
from ..translations import text as tr


class ModelInput(QComboBox):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.activated.connect(self.choose_reference)

    def set_provider(self, provider, text=''):
        blocker = QSignalBlocker(self)
        self.clear()
        suggestions = MODEL_SUGGESTIONS.get(provider, ())
        for model in suggestions:
            self.addItem(model, model)
        if suggestions:
            self.addItem(tr('其他（手动输入）'), None)
        self.setCurrentIndex(-1)
        self.setEditText(text)
        self.lineEdit().setPlaceholderText(
            tr('输入模型名称，或展开参考选项') if suggestions else tr('填写自定义模型名称'))
        self.setToolTip(tr('模型名称可自由输入。参考列表核对日期：') + MODEL_CATALOG_DATE)
        blocker.unblock()

    def choose_reference(self, index):
        if self.itemData(index) is None:
            self.setCurrentIndex(-1)
            self.setEditText('')
            self.lineEdit().setFocus()

    def text(self):
        return self.currentText()

    def setText(self, text):
        # Preserve arbitrary saved IDs instead of silently selecting a preset.
        self.setCurrentIndex(-1)
        self.setEditText(text)
