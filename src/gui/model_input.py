"""Editable model name with optional provider-specific reference choices."""

from aqt.qt import QComboBox, QSignalBlocker, QInputDialog

from ..service.ai_models import MODEL_SUGGESTIONS, MODEL_CATALOG_DATE, OTHER_MODELS
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
        self.provider = provider
        suggestions = MODEL_SUGGESTIONS.get(provider, ())[:10]
        for model in suggestions:
            self.addItem(model, model)
        if suggestions:
            self.addItem(tr('其他（旧模型 / 手动输入）'), None)
        self.setCurrentIndex(-1)
        self.setEditText(text)
        self.lineEdit().setPlaceholderText(
            tr('输入模型名称，或展开参考选项') if suggestions else tr('填写自定义模型名称'))
        self.setToolTip(tr('模型名称可自由输入。参考列表核对日期：') + MODEL_CATALOG_DATE)
        blocker.unblock()

    def choose_reference(self, index):
        if self.itemData(index) is None:
            older = OTHER_MODELS.get(getattr(self, 'provider', 'custom'), ())
            if older:
                text, ok = QInputDialog.getItem(self, tr('其他模型'), tr('旧模型可能已停用，请确认服务支持；也可直接输入模型 ID：'), list(older), 0, True)
                if ok:
                    self.setText(text)
                    return
            self.setCurrentIndex(-1)
            self.setEditText('')
            self.lineEdit().setFocus()

    def text(self):
        return self.currentText()

    def setText(self, text):
        # Preserve arbitrary saved IDs instead of silently selecting a preset.
        self.setCurrentIndex(-1)
        self.setEditText(text)
