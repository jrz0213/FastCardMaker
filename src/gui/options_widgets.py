"""Reusable configuration controls: wheel-safe combo and editable tab bar."""

from aqt.qt import *

BROWSER_TAB_STYLE = '''
    QTabBar::tab { min-width: 96px; padding: 7px 10px;
        border: 1px solid palette(mid); border-bottom: none;
        border-top-left-radius: 6px; border-top-right-radius: 6px;
        margin-right: 3px; background-color: palette(button); }
    QTabBar::tab:selected { background-color: palette(base); }
    QTabBar::tab:hover:!selected { background-color: palette(midlight); }
'''


class NoScrollComboBox(QComboBox):
    """强制忽略鼠标滚轮事件的下拉框，防止误触改变配置"""
    def wheelEvent(self, event):
        event.ignore()


class ProfileTabs(QTabBar):
    """Browser-like tabs with the existing profile-list controller interface."""
    currentRowChanged = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self.setExpanding(False)
        self.setTabsClosable(True)
        self.setUsesScrollButtons(True)
        self.setStyleSheet(BROWSER_TAB_STYLE)
        self.currentChanged.connect(self.currentRowChanged.emit)

    def addItem(self, label):
        self.addTab(label)

    def setCurrentRow(self, index):
        self.setCurrentIndex(index)

    def currentRow(self):
        return self.currentIndex()

    def takeItem(self, index):
        self.removeTab(index)

    def item(self, index):
        owner = self
        class Item:
            def setText(self, text):
                owner.setTabText(index, text)
            def text(self):
                return owner.tabText(index)
        return Item()

class CTabBar(QTabBar):
    def __init__(self, parent=None, parent_dialog=None):
        super(CTabBar, self).__init__(parent)
        self.parent_dialog = parent_dialog
        self.setTabsClosable(False)
        self.setMovable(False)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setUsesScrollButtons(True)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setObjectName('fwqConfigurationBar')
        self.setStyleSheet(BROWSER_TAB_STYLE)
        self._editor = QLineEdit(self)
        self._editor.setWindowFlags(Qt.WindowType.Popup)
        self._editor.setMaxLength(20)
        self._editor.editingFinished.connect(self.handleEditingFinished)
        self._editor.installEventFilter(self)

        f = self.font()
        f.setBold(True)
        self.setFont(f)

    def eventFilter(self, widget, event):
        bhide = False
        if event.type() == QEvent.Type.MouseButtonPress:
            if not self._editor.geometry().contains(event.globalPosition().toPoint()):
                bhide = True
        if not bhide:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Escape:
                    bhide = True
        if bhide:
            self.hideEditor()
            return True
        return QTabBar.eventFilter(self, widget, event)

    def mouseDoubleClickEvent(self, event):
        index = self.tabAt(event.pos())
        if index >= 0:
            self.editTab(index)

    def editTab(self, index):
        rect = self.tabRect(index)
        self._editor.setFixedSize(rect.size())
        self._editor.move(self.parent().mapToGlobal(rect.topLeft()))
        self._editor.setText(self.tabText(index))
        if not self._editor.isVisible():
            self._editor.show()
        self._editor.selectAll()
        self._editor.setEnabled(True)
        self._editor.setFocus()

    def hideEditor(self):
        if self._editor.isVisible():
            self._editor.setEnabled(False)
            self._editor.clearFocus()
            self._editor.hide()

    def handleEditingFinished(self):
        index = self.currentIndex()
        if index >= 0:
            self.hideEditor()
            if self._editor.text() and self._editor.text() != self.tabText(index):
                self.setTabText(index, self._editor.text())
                if hasattr(self.parent_dialog, '_is_dirty'):
                    self.parent_dialog._is_dirty = True
