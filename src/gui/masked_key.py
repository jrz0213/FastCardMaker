"""Partial key preview; editing uses Qt's password mode and real key value."""
from aqt.qt import QLineEdit, QSignalBlocker


def preview(value):
    return value[:3] + '*' * 8 + value[-3:] if len(value) > 6 else '*' * len(value)


class MaskedKeyEdit(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._value = ''
        self._editing = False
        self.textEdited.connect(self._edited)

    def _edited(self, value):
        self._value = value

    def text(self):
        return super().text() if self._editing else self._value

    def setText(self, value):
        self._value = value
        self.setEchoMode(QLineEdit.EchoMode.Password if self._editing else QLineEdit.EchoMode.Normal)
        super().setText(value if self._editing else preview(value))

    def clear(self):
        self.setText('')

    def focusInEvent(self, event):
        blocker = QSignalBlocker(self)
        self._editing = True
        self.setEchoMode(QLineEdit.EchoMode.Password)
        super().setText(self._value)
        del blocker
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._value = super().text()
        blocker = QSignalBlocker(self)
        self._editing = False
        self.setEchoMode(QLineEdit.EchoMode.Normal)
        super().setText(preview(self._value))
        del blocker
        super().focusOutEvent(event)
