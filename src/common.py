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

from operator import itemgetter

from anki.hooks import addHook, remHook, wrap
from aqt import mw
from aqt.addcards import AddCards
from aqt.qt import *
from aqt.utils import downArrow, shortcut, showInfo

from .context import APP_ICON, Config, config
from .gui import show_about_dialog, show_options  # , check_updates
from .lang import _
from .query import query_from_browser, query_from_editor_fields
from .service import service_pool
from .utils import get_icon

__all__ = [
    'browser_menu', 'customize_addcards', 'config_menu', 'context_menu'
]  # 'check_updates',

have_setup = False
my_shortcut = ''

_OK_ICON = get_icon('ok.png')
_NULL_ICON = get_icon('null.png')


def set_options_def(mid, i):
    conf = config.get_maps(mid)
    conf = {'list': [conf], 'def': 0} if isinstance(conf, list) else conf
    if conf['def'] != i:
        conf['def'] = i
        data = dict()
        data[mid] = conf
        config.update(data)


# end set_options_def


def browser_menu():
    """
    add add-on's menu to browser window
    """

    def on_setup_menus(browser):
        """
        on browser setupMenus was called
        """
        # main menu
        menu = browser.form.menubar.addMenu("FastCM")

        # menu gen
        def init_fastcm_menu():
            try:
                menu.clear()
            except RuntimeError:
                remHook('config.update', init_fastcm_menu)
                return
            # Query Selected
            action = QAction(_('QUERY_SELECTED'), browser)
            action.triggered.connect(lambda: query_from_browser(browser))
            action.setShortcut(QKeySequence(my_shortcut))
            menu.addAction(action)
            from .gui.type_query import show_type_query
            from .translations import text as tr
            action = QAction(tr('全类型查询'), browser)
            action.triggered.connect(lambda: show_type_query(browser))
            menu.addAction(action)
            # Options
            action = QAction(_('OPTIONS'), browser)

            def _show_options():
                model_id = -1
                for note_id in browser.selectedNotes():
                    note = browser.mw.col.get_note(note_id)
                    model_id = note.note_type()['id']
                    break
                show_options(browser, model_id)

            action.triggered.connect(_show_options)
            menu.addAction(action)

            # Default configs
            from .gui.task_progress import TaskMenuAction
            menu.addAction(TaskMenuAction(menu))
            from .gui.result_recovery import show_recovery
            from .translations import text as tr
            recovery = QAction(tr('恢复未写入结果'), menu)
            recovery.triggered.connect(lambda: show_recovery(browser))
            menu.addAction(recovery)
            menu.addSeparator()
            b = False
            for m in sorted(
                    browser.mw.col.models.all(), key=itemgetter("name")):
                conf = config.get_maps(m['id'])
                conf = {
                    'list': [conf],
                    'def': 0
                } if isinstance(conf, list) else conf
                maps_list = conf['list']
                if len(maps_list) > 1:
                    submenu = menu.addMenu(m['name'])
                    for i, maps in enumerate(maps_list):
                        submenu.addAction(
                            _OK_ICON if i == conf['def'] else _NULL_ICON,
                            _('CONFIG_INDEX') % (i + 1) if isinstance(
                                maps, list) else maps['name'],
                            lambda mid=m['id'], i=i: set_options_def(mid, i))
                    b = True
            if b:
                menu.addSeparator()

            # # check update
            # action = QAction(_('CHECK_UPDATE'), browser)
            # action.triggered.connect(lambda: check_updates(background=False, parent=browser))
            # menu.addAction(action)

            # About
            action = QAction(_('ABOUT'), browser)
            action.triggered.connect(lambda: show_about_dialog(browser))
            menu.addAction(action)

        # end init_fastcm_menu
        init_fastcm_menu()
        addHook('config.update', init_fastcm_menu)

    addHook('browser.setupMenus', on_setup_menus)


def customize_addcards():
    """
    add button to addcards window
    """

    def add_query_button(self):
        '''
        add a button in add card window
        '''
        bb = self.form.buttonBox
        ar = QDialogButtonBox.ButtonRole.ActionRole
        # button
        fastcmBtn = QPushButton(_("QUERY") + u" " + downArrow())
        fastcmBtn.setShortcut(QKeySequence(my_shortcut))
        fastcmBtn.setToolTip(_(u"Shortcut: %s") % shortcut(my_shortcut))
        bb.addButton(fastcmBtn, ar)

        # signal
        def onQuery(e):
            if isinstance(e, QMouseEvent):
                if e.buttons() & Qt.MouseButton.LeftButton:
                    menu = QMenu(self)
                    menu.addAction(
                        _("ALL_FIELDS"),
                        lambda: query_from_editor_fields(self.editor))  # ,QKeySequence(my_shortcut))
                    # default options
                    mid = self.editor.note.model()['id']
                    conf = config.get_maps(mid)
                    conf = {
                        'list': [conf],
                        'def': 0
                    } if isinstance(conf, list) else conf
                    maps_list = conf['list']
                    if len(maps_list) > 1:
                        menu.addSeparator()
                        for i, maps in enumerate(maps_list):
                            menu.addAction(
                                _OK_ICON if i == conf['def'] else _NULL_ICON,
                                _('CONFIG_INDEX') % (i + 1) if isinstance(
                                    maps, list) else maps['name'],
                                lambda mid=mid, i=i: set_options_def(mid, i))
                        menu.addSeparator()
                    # end default options
                    menu.addAction(_("OPTIONS"), lambda: show_options(self, self.editor.note.model()['id']))
                    menu.exec(
                        fastcmBtn.mapToGlobal(QPoint(0, fastcmBtn.height())))
            else:
                query_from_editor_fields(self.editor)

        fastcmBtn.mousePressEvent = onQuery
        fastcmBtn.clicked.connect(onQuery)

    AddCards.setupButtons = wrap(AddCards.setupButtons, add_query_button,
                                 "after")


def config_menu():
    """
    add menu to anki window menebar
    """
    from .gui.type_query import show_type_query
    from .gui.task_progress import TaskMenuAction
    from .translations import text as tr
    menu = mw.menuBar().addMenu('FastCM')
    menu.addAction(tr('全类型查询'), lambda: show_type_query())
    menu.addAction(_('OPTIONS'), lambda: show_options())
    class MainProgressAction(TaskMenuAction):
        def refresh(self):
            super().refresh()
            self.setEnabled(True)

        def open_progress(self):
            if self.job is None:
                showInfo(tr('暂无后台任务。'))
            else:
                super().open_progress()
    progress = MainProgressAction(menu)
    menu.addAction(progress)
    menu.addAction(_('ABOUT'), lambda: show_about_dialog())


def context_menu():
    """mouse right click menu"""

    def on_setup_menus(web_view, menu):
        """
        add context menu to webview
        """
        if not isinstance(web_view.editor.currentField, int):
            return
        current_model_id = web_view.editor.note.model()['id']
        conf = config.get_maps(current_model_id)
        maps_list = conf if isinstance(conf, list) else conf['list']
        curr_flds = []
        names = []
        for i, maps in enumerate(maps_list):
            maps = maps if isinstance(maps, list) else maps['fields']
            word_ord = 0
            for mord, m in enumerate(maps):
                if m.get('word_checked', False):
                    word_ord = mord
                    break
            if web_view.editor.currentField != word_ord:
                each = maps[web_view.editor.currentField]
                ignore = each.get('ignore', False)
                if not ignore:
                    dict_unique = each.get('dict_unique', '').strip()
                    dict_fld_ord = each.get('dict_fld_ord', -1)
                    fld_ord = each.get('fld_ord', -1)
                    if dict_unique and dict_fld_ord != -1 and fld_ord != -1:
                        s = None
                        try:
                            s = service_pool.get(dict_unique, timeout=0.1)
                            if s and s.support and s.fields and 0 <= dict_fld_ord < len(s.fields):
                                name = s.title + ' :-> ' + s.fields[dict_fld_ord]
                                if name not in names:
                                    names.append(name)
                                    curr_flds.append({'name': name, 'def': i})
                        finally:
                            service_pool.put(s)


        submenu = menu.addMenu(_('QUERY'))
        submenu.addAction(
            _('ALL_FIELDS'), lambda: query_from_editor_fields(web_view.editor))  # ,QKeySequence(my_shortcut))
        if len(curr_flds) > 0:
            # quer hook method
            def query_from_editor_hook(i):
                conf = config.get_maps(current_model_id)
                maps_old_def = 0 if isinstance(conf, list) else conf.get(
                    'def', 0)
                set_options_def(current_model_id, i)
                query_from_editor_fields(
                    web_view.editor, fields=[web_view.editor.currentField])
                set_options_def(current_model_id, maps_old_def)

            # sub menu
            # flds_menu = submenu.addMenu(_('CURRENT_FIELDS'))
            submenu.addSeparator()
            for c in curr_flds:
                submenu.addAction(
                    c['name'], lambda i=c['def']: query_from_editor_hook(i))
            submenu.addSeparator()
        submenu.addAction(_("OPTIONS"), lambda: show_options(web_view, web_view.editor.note.model()['id']))

    addHook('EditorWebView.contextMenuEvent', on_setup_menus)
