"""Prompt editor used in the data-item cell for AI mapping rows."""

from ...translations import text as tr

from aqt.qt import *
from ...service.ai_config import is_ai
from ..options_widgets import NoScrollComboBox


class PromptCombo(NoScrollComboBox):
    """A single-line prompt preview with an overlay editor in its popup."""

    def __init__(self, text='', parent=None, source_field=None):
        super().__init__(parent)
        self.source_field = source_field or (lambda: tr('单词'))
        self.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.setMinimumContentsLength(12)
        self.addItem(tr('填写 AI 提示词…'))
        self.setToolTip(tr('点击展开编辑；使用 {{字段名}} 引用普通字段，不能引用 AI 输出字段。'))
        # Native Popup windows grab the keyboard and can disrupt Windows IMEs.
        # A focusable tool window still overlays the mapping rows without a grab.
        self.popup = QFrame(self, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint)
        self.popup.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self.popup)
        layout.setContentsMargins(6, 6, 6, 6)
        self.templates = QComboBox(self.popup)
        self.templates.addItem(tr('选择提示词模板（替换当前内容）'), '')
        for label, template in [
            (tr('意思与词性'), tr('解释 %s 的常见中文意思，注明词性，并给一个简短例句。')),
            (tr('例句'), tr('为 %s 给出三个自然、简短的英文例句，并附中文翻译。')),
            (tr('相关词与辨析表格'), tr('列出与 %s 相关的常见词，用 Markdown 表格对比单词、中文意思和关系；区分近义词、同类词和拼写相似词。')),
        ]:
            self.templates.addItem(label, template)
        layout.addWidget(self.templates)
        self.templates.activated.connect(self.use_template)
        self.editor = QPlainTextEdit(self.popup)
        self.editor.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.editor.setInputMethodHints(Qt.InputMethodHint.ImhNone)
        self.editor.setPlaceholderText(tr('填写提示词，例如：解释 {{单词}} 在 {{例句}} 中的含义'))
        self.composing = False
        self.popup.installEventFilter(self)
        layout.addWidget(self.editor)
        self.editor.textChanged.connect(self.update_preview)
        self.setPlainText(text)

    def use_template(self, index):
        template = self.templates.itemData(index)
        if template:
            self.setPlainText(template % ('{{' + self.source_field() + '}}'))
            self.templates.setCurrentIndex(0)
            self.editor.setFocus()

    def toPlainText(self):
        return self.editor.toPlainText()

    def setPlainText(self, text):
        self.editor.setPlainText(text)

    def update_preview(self):
        preview = ' '.join(self.toPlainText().split())
        self.setItemText(0, preview[:100] if preview else tr('填写 AI 提示词…'))

    def showPopup(self):
        if not self.isEnabled():
            return
        screen = self.screen().availableGeometry()
        origin = self.mapToGlobal(QPoint(0, self.height()))
        width = min(max(self.width(), 360), screen.width())
        height = min(220, screen.height())
        x = max(screen.left(), min(origin.x(), screen.right() - width + 1))
        y = origin.y()
        if y + height > screen.bottom() + 1:
            y = self.mapToGlobal(QPoint(0, 0)).y() - height
        y = max(screen.top(), min(y, screen.bottom() - height + 1))
        self.popup.setGeometry(x, y, width, height)
        QApplication.instance().installEventFilter(self)
        self.popup.show()
        self.popup.activateWindow()
        self.editor.setFocus(Qt.FocusReason.OtherFocusReason)

    def hidePopup(self):
        if self.popup.isVisible():
            QApplication.inputMethod().commit()
        self.popup.hide()

    def eventFilter(self, obj, event):
        if obj is self.popup and event.type() == QEvent.Type.Hide:
            QApplication.instance().removeEventFilter(self)
            self.composing = False
        if not self.popup.isVisible():
            return False
        if obj is self.editor and event.type() == QEvent.Type.InputMethod:
            self.composing = bool(event.preeditString())
            return False
        if obj is self.editor and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
            # Let the IME cancel its current composition before closing the editor.
            if self.composing:
                return False
            self.hidePopup()
            self.window().activateWindow()
            self.setFocus()
            return True
        if event.type() == QEvent.Type.MouseButtonPress:
            point = event.globalPosition().toPoint()
            preview = QRect(self.mapToGlobal(QPoint(0, 0)), self.size())
            if not self.popup.geometry().contains(point) and not preview.contains(point):
                self.hidePopup()
        # QComboBox's internal filter must not process the text editor's IME events.
        return False

    def hideEvent(self, event):
        self.hidePopup()
        super().hideEvent(event)

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.EnabledChange and not self.isEnabled():
            self.hidePopup()


def prompt_controls(combo, field_combo, saved_prompt, parent):
    def source_field():
        for row in parent._options:
            if row['word_check_btn'].isChecked():
                return row['model']['fld_name']
        return parent._model['flds'][0]['name']
    editor = PromptCombo(saved_prompt, source_field=source_field)
    editor.setStyleSheet(field_combo.styleSheet())
    editor.setMinimumWidth(field_combo.minimumWidth())
    stack = QStackedWidget()
    stack.addWidget(field_combo)
    stack.addWidget(editor)
    # Hidden pages and popup editors must not change the mapping row height.
    stack.setFixedHeight(max(field_combo.minimumHeight(), field_combo.sizeHint().height()))
    def refresh():
        stack.setCurrentIndex(1 if is_ai(combo.currentData()) else 0)
        editor.setEnabled(field_combo.isEnabled())
        if stack.currentIndex() != 1:
            editor.hidePopup()
    def dirty():
        if not parent._is_building and parent._parent_dialog:
            parent._parent_dialog._is_dirty = True
    editor.editor.textChanged.connect(dirty)
    refresh()
    return stack, editor, refresh
