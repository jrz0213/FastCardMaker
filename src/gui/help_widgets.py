"""Small, consistent help buttons for explanatory text outside the main workflow."""
from aqt.qt import *
from .base import Dialog
from ..translations import text as tr


def show_help(parent, title, content):
    dialog = Dialog(parent, title)
    dialog.resize(640, 420)
    layout = QVBoxLayout(dialog)
    viewer = QTextBrowser()
    viewer.setPlainText(content() if callable(content) else content)
    layout.addWidget(viewer)
    dialog.exec()


def with_help(widget, title, content):
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    if isinstance(widget, QToolButton):
        layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
        layout.addStretch(1)
    else:
        layout.addWidget(widget, 1)
    button = QToolButton()
    button.setText('?')
    button.setAutoRaise(True)
    button.setAccessibleName(tr('帮助') + ': ' + title)
    button.setToolTip(title)
    button.clicked.connect(lambda: show_help(row, title, content))
    layout.addWidget(button)
    return row
