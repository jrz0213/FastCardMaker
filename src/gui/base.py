# -*- coding:utf-8 -*-
#
# Copyright (C) 2018 sthoo <sth201807@gmail.com>
#
# Support: Report an issue at https://github.com/sth2018/FastWordQuery/issues
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# any later version; http://www.gnu.org/copyleft/gpl.html.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program. If not, see <http://www.gnu.org/licenses/>.

from anki.utils import is_mac
from aqt.qt import *

from ..context import APP_ICON
from copy import deepcopy

__all__ = ['Dialog', 'WIDGET_SIZE']


class Dialog(QDialog):
    '''
    Base used for all dialog windows.
    '''

    def __init__(self, parent, title):
        '''
        Set the modal status for the dialog, sets its layout to the
        return value of the _ui() method, and sets a default title.
        '''

        self._title = title if ('FastCM' in title or 'FastCard Maker' in title) else 'FastCM - ' + title
        self._parent = parent
        super(Dialog, self).__init__(parent)

        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self.setWindowIcon(APP_ICON)
        self.setWindowTitle(self._title)
        
        # mac compatible
        if is_mac:
            QApplication.setStyle('Fusion')

    def watch_changes(self, reader):
        self._snapshot_reader = reader
        self._initial_values = deepcopy(reader())

    def widget_values(self):
        values = []
        for widget in self.findChildren(QWidget):
            if isinstance(widget, QComboBox):
                values.append(widget.currentText() if widget.isEditable() else widget.currentData())
            elif isinstance(widget, QLineEdit):
                # Spin boxes and editable combos already contribute their value.
                if not isinstance(widget.parentWidget(), (QAbstractSpinBox, QComboBox)):
                    values.append(widget.text())
            elif isinstance(widget, QPlainTextEdit):
                values.append(widget.toPlainText())
            elif isinstance(widget, QCheckBox):
                values.append(widget.isChecked())
            elif isinstance(widget, QSpinBox):
                values.append(widget.value())
            elif isinstance(widget, QListWidget):
                values.append([(widget.item(i).text(), widget.item(i).checkState().value) for i in range(widget.count())])
        return values

    def reject(self):
        reader = getattr(self, '_snapshot_reader', None)
        if reader and reader() != self._initial_values:
            from ..translations import text as tr
            answer = QMessageBox(self)
            answer.setWindowTitle(tr('确认退出'))
            answer.setText(tr('设置已修改，是否保存？'))
            save = answer.addButton(tr('保存'), QMessageBox.ButtonRole.AcceptRole)
            discard = answer.addButton(tr('不保存'), QMessageBox.ButtonRole.DestructiveRole)
            answer.addButton(QMessageBox.StandardButton.Cancel)
            answer.exec()
            if answer.clickedButton() is save:
                self.accept()
                return
            if answer.clickedButton() is not discard:
                return
        super().reject()


class WidgetSize(object):
    '''
    constant values
    '''
    dialog_width = 850
    dialog_height_margin = 146
    map_min_height = 0
    map_max_height = 30
    map_fld_width = 100
    map_dictname_width = 250
    map_dict_width = 160
    map_field_width = 200


WIDGET_SIZE = WidgetSize()
