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

from aqt import mw
from aqt.qt import *

from ..constants import Template
from ..context import config
from ..lang import _
from ..translations import text as tr
from ..service.refresh import get_updater
from .dictmanager import DictManageDialog
from .foldermanager import FoldersManageDialog
from .options import OptionsDialog

__all__ = ['show_options', 'show_fm_dialog', 'show_about_dialog']
_open_options = []


def show_fm_dialog(browser=None):
    '''open dictionary folder manager window'''
    parent = mw if browser is None else browser
    fm_dialog = DictManageDialog(parent)
    fm_dialog.management_tabs.setCurrentIndex(2)
    fm_dialog.activateWindow()
    fm_dialog.raise_()
    if fm_dialog.exec() == QDialog.DialogCode.Accepted:
        get_updater().request(folder_sync=True)
    fm_dialog.destroy()
    # reshow options window
    show_options(browser)


def show_dm_dialog(browser=None):
    parent = mw if browser is None else browser
    dm_dialog = DictManageDialog(parent)
    dm_dialog.activateWindow()
    dm_dialog.raise_()
    if dm_dialog.exec() == QDialog.DialogCode.Accepted:
        get_updater().request(folder_sync=True)
    dm_dialog.destroy()
    # reshow options window
    show_options(browser)


def show_options(browser=None, model_id=-1, callback=None, *args, **kwargs):
    '''open options window'''
    parent = mw if browser is None else browser
    config.read()
    from .config_sync import check_settings
    if not check_settings(parent):
        return
    opt_dialog = OptionsDialog(parent, tr('FastCard Maker 核心配置台'), model_id)
    opt_dialog.activateWindow()
    opt_dialog.raise_()
    _open_options.append(opt_dialog)
    def finished(result):
        if opt_dialog in _open_options:
            _open_options.remove(opt_dialog)
        opt_dialog.deleteLater()
        if result == QDialog.DialogCode.Accepted:
            if callable(callback):
                callback(*args, **kwargs)
        elif result == 1001:
            show_fm_dialog(parent)
        elif result == 1002:
            show_dm_dialog(parent)
    opt_dialog.finished.connect(finished)
    # Modeless configuration and no nested event loop: queries can continue
    # while the user works in the browser or main Anki window.
    opt_dialog.show()
    return opt_dialog


def show_about_dialog(parent):
    '''open about dialog'''
    QMessageBox.about(parent, _('ABOUT'), Template.tmpl_about)
