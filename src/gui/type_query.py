"""Explicit, saved-configuration queries for one or more complete note types."""
from copy import deepcopy
from aqt import mw
from aqt.qt import *
from ..context import config
from ..translations import text as tr
from ..utils.media import profile_token
from .help_widgets import with_help


def selected_model_ids(browser):
    if browser is None:
        return set()
    ids = list(browser.selectedNotes())
    models = set()
    for offset in range(0, len(ids), 500):
        chunk = ids[offset:offset + 500]
        models.update(browser.mw.col.db.list(
            'select distinct mid from notes where id in (%s)' % ','.join('?' for _ in chunk), *chunk))
    return models


def configurations(mid):
    value = deepcopy(config.get_maps(mid))
    value = {'list': [value], 'def': 0} if isinstance(value, list) else value
    if not isinstance(value, dict):
        return [], 0
    return value.get('list', []), value.get('def', 0)


class TypeQueryDialog(QDialog):
    def __init__(self, parent=None, selected=None):
        super().__init__(parent)
        self.token = profile_token()
        self.setWindowTitle('FastCM - ' + tr('全类型查询'))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(660, 430)
        self.rows, self.notes, self.plan = [], [], []
        self.preparing = False
        layout = QVBoxLayout(self)
        note = QLabel(tr('选择笔记类型及配置，查询这些类型的全部笔记。'))
        note.setWordWrap(True)
        layout.addWidget(with_help(note, tr('查询范围'), tr(
            '查询会处理勾选笔记类型的全部笔记，不限于当前牌组或浏览器选中项，使用右侧选择的已保存配置。'
            '从浏览器打开时默认勾选选中笔记所属类型；从首页打开时默认不选。未勾选类型不会运行。'
            '只想处理选中笔记，请使用“查询选中项”。')))
        self.types = QTreeWidget()
        self.types.setHeaderLabels([tr('选择笔记类型'), tr('使用的配置')])
        self.types.setStyleSheet('QTreeWidget::item { padding: 7px 4px; } QHeaderView::section { padding: 8px; font-weight: bold; }')
        self.types.setRootIsDecorated(False)
        self.types.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        for model in sorted(mw.col.models.all(), key=lambda m: m['name']):
            item = QTreeWidgetItem(self.types, [model['name']])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(0, Qt.CheckState.Checked if model['id'] in (selected or set()) else Qt.CheckState.Unchecked)
            combo = QComboBox()
            choices, default = configurations(model['id'])
            for index, value in enumerate(choices):
                combo.addItem(value.get('name', tr('配置 %s') % (index + 1)) if isinstance(value, dict)
                              else tr('配置 %s') % (index + 1), index)
            combo.setCurrentIndex(default if type(default) is int and 0 <= default < len(choices) else 0)
            self.types.setItemWidget(item, 1, combo)
            self.rows.append((model, item, combo))
            combo.setEnabled(item.checkState(0) == Qt.CheckState.Checked)
        layout.addWidget(self.types)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.query_button = QPushButton(tr('开始查询'))
        self.query_button.clicked.connect(self.run)
        close = QPushButton(tr('取消'))
        close.clicked.connect(self.close)
        buttons.addWidget(self.query_button)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.loader = QTimer(self)
        self.loader.setInterval(0)
        self.loader.timeout.connect(self.gather)
        self.types.itemChanged.connect(self.selection_changed)
        self.selection_changed()

    def selection_changed(self, *_):
        selected = 0
        for _, item, combo in self.rows:
            checked = item.checkState(0) == Qt.CheckState.Checked
            combo.setEnabled(checked)
            selected += checked
        self.query_button.setEnabled(bool(selected) and not self.preparing)
        self.status.setText(tr('已选择 %s 个笔记类型') % selected)

    def run(self):
        if self.preparing or self.token != profile_token():
            return
        from ..query.background import active_job
        if active_job():
            active_job().show_progress()
            self.status.setText(tr('已有更新任务正在运行，请完成或取消后再开始。'))
            return
        from ..service.ai_validation import validate_ai_mappings
        self.plan, self.notes = [], []
        try:
            for model, item, combo in self.rows:
                if item.checkState(0) != Qt.CheckState.Checked:
                    continue
                current = mw.col.models.get(model['id'])
                if not current:
                    raise ValueError(tr('笔记类型不存在，请重新打开设置。'))
                choices, _ = configurations(model['id'])
                index = combo.currentData()
                if index is None or not 0 <= index < len(choices):
                    raise ValueError(tr('请先保存所选笔记类型的配置。'))
                value = choices[index]
                maps = value.get('fields', []) if isinstance(value, dict) else value
                if not maps or not any(m.get('dict_unique') and not m.get('ignore', True) and not m.get('word_checked') for m in maps):
                    raise ValueError(tr('所选配置没有可更新的字段：%s') % current['name'])
                validate_ai_mappings(maps, [f['name'] for f in current['flds']])
                self.plan.append((current['id'], deepcopy(maps), 0))
        except ValueError as error:
            self.status.setText(str(error))
            self.plan = []
            return
        if not self.plan:
            self.status.setText(tr('请至少勾选一个笔记类型。'))
            return
        self.preparing = True
        self.types.setEnabled(False)
        self.query_button.setEnabled(False)
        self.status.setText(tr('正在准备笔记…'))
        self.loader.start()

    def gather(self):
        if self.token != profile_token() or not getattr(mw, 'col', None):
            self.close()
            return
        try:
            if self.plan:
                mid, maps, cursor = self.plan[0]
                ids = mw.col.db.list('select id from notes where mid = ? and id > ? order by id limit 200', mid, cursor)
                for nid in ids:
                    note = mw.col.get_note(nid)
                    if note.note_type()['id'] == mid:
                        note._query_mappings = deepcopy(maps)
                        self.notes.append(note)
                if ids:
                    self.plan[0] = (mid, maps, ids[-1])
                else:
                    self.plan.pop(0)
                self.status.setText(tr('正在准备笔记：%s') % len(self.notes))
                return
            self.loader.stop()
            self.preparing = False
            self.types.setEnabled(True)
            self.query_button.setEnabled(True)
            if not self.notes:
                self.status.setText(tr('所选类型没有笔记。'))
                return
            from ..query.background import active_job, start_query_session
            if active_job():
                self.notes = []
                active_job().show_progress()
                self.status.setText(tr('已有更新任务正在运行，请完成或取消后再开始。'))
                return
            start_query_session(self.notes, parent=self.parentWidget())
            self.notes = []
            self.close()
        except Exception as error:
            from ..utils.logger import logger
            logger.warning('Preparing a note-type query failed: %s', type(error).__name__)
            self.loader.stop()
            self.preparing = False
            self.notes = []
            self.types.setEnabled(True)
            self.query_button.setEnabled(True)
            self.status.setText(tr('准备笔记失败，请重新打开窗口重试。'))

    def closeEvent(self, event):
        self.loader.stop()
        self.notes, self.plan = [], []
        super().closeEvent(event)

    def reject(self):
        self.loader.stop()
        self.notes, self.plan = [], []
        super().reject()


def close_type_queries():
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, TypeQueryDialog):
            widget.close()


def show_type_query(browser=None):
    parent = browser or mw
    old = getattr(parent, '_fwq_type_query', None)
    if old is not None:
        old.close()
        old.deleteLater()
    dialog = TypeQueryDialog(parent, selected_model_ids(browser))
    parent._fwq_type_query = dialog
    dialog.show()
    dialog.raise_()
    return dialog
