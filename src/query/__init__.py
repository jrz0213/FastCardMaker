#-*- coding:utf-8 -*-
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

from collections import defaultdict
import os
import shutil
import unicodedata

from aqt import mw
from aqt.qt import QTimer, QWidget
from aqt.utils import showInfo, showText, tooltip

from .worker import QueryWorkerManager
from .common import promot_choose_css, inspect_note

from ..constants import Endpoint, Template
from ..context import config
from ..lang import _
from ..translations import text as tr
from ..gui import ProgressWindow
from ..service import service_manager, service_pool, QueryResult, copy_static_file
from ..service.base import LocalService
from ..utils import MapDict, wrap_css
from queue import Queue, Empty
__all__ = ['query_from_browser', 'query_from_editor_fields']


def query_from_browser(browser):
    """
    Query word from Browser
    """

    if not browser:
        return

    notes = [browser.mw.col.get_note(note_id)
             for note_id in browser.selectedNotes()]

    if len(notes) == 1:
        query_from_editor_fields(browser.editor)
    else:
        query_all(notes)
        # browser.model.reset()


def query_from_editor_fields(editor, fields=None):
    """Start only after the editor has acknowledged its latest webview contents."""
    if editor is None:
        return
    import weakref
    reference = weakref.ref(editor)
    finished = False
    def closed():
        current = reference()
        try:
            if current is None:
                return True
            parent = current.parentWindow
            return isinstance(parent, QWidget) and not parent.isVisible()
        except (RuntimeError, AttributeError):
            return True
    def timeout():
        nonlocal finished
        if not finished:
            finished = True
            if not closed():
                tooltip(tr('无法确认编辑器中的最新内容，已跳过更新并保留原内容。'))
    def start(note, modern=False):
        nonlocal finished
        if finished or closed():
            return
        finished = True
        current = reference()
        if note is None:
            return
        _, _, maps = inspect_note(note)
        if not any(item.get('dict_unique') and not item.get('ignore', True) for item in maps):
            from ..gui import show_options
            tooltip(_('PLS_SET_DICTIONARY_FIELDS'))
            show_options(current.parentWindow, note.note_type()['id'], query_from_editor_fields,
                         current, fields)
            return
        original = note
        def valid_editor():
            active = reference()
            if closed():
                return False
            if modern:
                return getattr(active, 'nid', None) == original.id
            return getattr(active, 'note', None) is original
        from .background import start_query_session
        return start_query_session([original], flush=not current.addMode, fields=fields,
                                   parent=current.parentWindow, editor=current,
                                   guard=valid_editor if current.addMode else None)
    def info_ready(info):
        nonlocal finished
        if finished or closed():
            return
        current = reference()
        if current.addMode or not getattr(info, 'id', None):
            finished = True
            tooltip(tr('新版添加窗口的笔记尚未保存，请先添加卡片后再查询，或使用旧版添加窗口。'))
            return
        try:
            note = mw.col.get_note(info.id)
            if note.note_type()['id'] != info.mid:
                timeout()
                return
            note.fields = list(info.fields)
            start(note, modern=True)
        except Exception:
            timeout()
    def saved():
        if finished or closed():
            return
        current = reference()
        read = getattr(current, 'get_note_info', None)
        if callable(read):
            read(info_ready)
        else:
            start(getattr(current, 'note', None))
    QTimer.singleShot(2500, timeout)
    try:
        save = getattr(editor, 'call_after_note_saved', None) or getattr(editor, 'saveNow', None)
        if callable(save):
            save(saved, keepFocus=True)
        else:
            saved()
    except (RuntimeError, AttributeError, TypeError):
        timeout()


def query_all(notes, flush=True, fields=None):
    if not notes:
        return
    from .background import start_query_session
    return start_query_session(notes, flush=flush, fields=fields)
