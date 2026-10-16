"""Field mapping tab lifecycle, selections, and configuration serialization."""

from aqt.qt import *
from ..translations import text as tr

from .mapping_controls import (
    add_dict_layout, fill_dict_combo_options, fill_field_combo_options,
)


class TabContent(QScrollArea):
    """Options tab content (Field Mapping Grid)"""
    def __init__(self, model, conf, services, controller, parent_dialog=None):
        super(TabContent, self).__init__()
        self._conf = conf
        self._model = model
        self._services = services
        self._controller = controller
        self._parent_dialog = parent_dialog
        self._last_checkeds = None
        self._options = list()
        self._was_built = False
        self._is_building = False # 防误触锁

        dicts = QWidget(self)
        self.dicts_layout = QGridLayout(dicts)
        self.dicts_layout.setContentsMargins(12, 12, 12, 12)
        self.dicts_layout.setHorizontalSpacing(12)
        self.dicts_layout.setVerticalSpacing(8)

        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setWidgetResizable(True)
        self.setWidget(dicts)

    def refresh_dict_combos(self, services):
        self._services = services
        for row in self._options:
            combo = row['dict_combo']
            current_unique = combo.itemData(combo.currentIndex())
            # Updating status labels must not trigger the user's dictionary-change
            # handler: clear()/addItem() temporarily select an empty/first item.
            blocker = QSignalBlocker(combo)
            try:
                self.fill_dict_combo_options(combo, current_unique, self._services)
                selected_unique = combo.itemData(combo.currentIndex())
                if selected_unique != current_unique or (not row['field_combo'].isEditable() and
                        self._controller.get_service_fields(selected_unique)):
                    field_combo = row['field_combo']
                    field_blocker = QSignalBlocker(field_combo)
                    try:
                        self.fill_field_combo_options(
                            field_combo, combo.currentText(), selected_unique,
                            field_combo.currentText(),
                            field_combo.itemData(field_combo.currentIndex()))
                    finally:
                        field_blocker.unblock()
                if 'refresh_prompt' in row:
                    row['refresh_prompt']()
            finally:
                blocker.unblock()

    def build_layout(self):
        if self._was_built:
            return

        self._is_building = True # 上锁，禁止此时触发脏标记
        del self._options[:]
        self._last_checkeds = None
        self._was_built = True

        model = self._model
        maps = self._conf

        header_font = QFont()
        header_font.setBold(True)

        lbl_field = QLabel(tr('字段（单选为来源）'))
        lbl_field.setFont(header_font)
        self.dicts_layout.addWidget(lbl_field, 0, 0)

        self.ignore_all_check_btn = QCheckBox(tr('忽略全部'))
        self.ignore_all_check_btn.setFont(header_font)
        self.ignore_all_check_btn.setChecked(True)
        self.ignore_all_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dicts_layout.addWidget(self.ignore_all_check_btn, 0, 1)
        self.ignore_all_check_btn.clicked.connect(self.ignore_all_check_changed)

        lbl_dict = QLabel(tr('内容来源（AI / 词典）'))
        lbl_dict.setFont(header_font)
        self.dicts_layout.addWidget(lbl_dict, 0, 2)

        lbl_extract = QLabel(tr('数据项 / 提示词'))
        lbl_extract.setFont(header_font)
        self.dicts_layout.addWidget(lbl_extract, 0, 3)

        self.skip_all_check_btn = QCheckBox(tr('全部跳过已有内容'))
        self.skip_all_check_btn.setFont(header_font)
        self.skip_all_check_btn.setChecked(True)
        self.skip_all_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.dicts_layout.addWidget(self.skip_all_check_btn, 0, 4)
        self.skip_all_check_btn.clicked.connect(self.skip_all_check_changed)

        lbl_cloze = QLabel(tr('完形填空'))
        lbl_cloze.setFont(header_font)
        self.dicts_layout.addWidget(lbl_cloze, 0, 5)
        for label in (lbl_field, lbl_dict, lbl_extract, lbl_cloze):
            label.setWordWrap(True)

        self.radio_group = QButtonGroup()
        for i, fld in enumerate(model['flds']):
            ord = fld['ord']
            name = fld['name']
            if maps:
                for j, each in enumerate(maps):
                    if each.get('fld_ord', -1) == ord or each.get('fld_name', '') == name:
                        each['fld_name'] = name
                        each['fld_ord'] = ord
                        self.add_dict_layout(i, **each)
                        break
                else:
                    self.add_dict_layout(i, fld_name=name, fld_ord=ord, word_checked=i == 0)
            else:
                self.add_dict_layout(i, fld_name=name, fld_ord=ord, word_checked=i == 0)

        current_row = self.dicts_layout.rowCount()
        self.dicts_layout.setRowStretch(current_row, 1)

        self.ignore_all_update()
        self.skip_all_update()

        # 统一的向上传递脏标记的回调
        def mark_dirty(*args):
            if not self._is_building and self._parent_dialog and hasattr(self._parent_dialog, '_is_dirty'):
                self._parent_dialog._is_dirty = True

        self.ignore_all_check_btn.clicked.connect(mark_dirty)
        self.skip_all_check_btn.clicked.connect(mark_dirty)

        self._is_building = False # 开锁，后续任何动作都会触发脏标记

    def add_dict_layout(self, i, **kwargs):
        return add_dict_layout(self, i, **kwargs)

    def fill_dict_combo_options(self, dict_combo, current_unique, services):
        return fill_dict_combo_options(self, dict_combo, current_unique, services)

    def fill_field_combo_options(self, field_combo, dict_combo_text,
                                 dict_combo_itemdata, dict_fld_name, dict_fld_ord, allow_default=False):
        return fill_field_combo_options(self, field_combo, dict_combo_text,
                                       dict_combo_itemdata, dict_fld_name, dict_fld_ord, allow_default=allow_default)

    @property
    def data(self):
        if not self._was_built:
            return self._conf
        maps = []
        for row in self._options:
            maps.append({
                'fld_name': row['model']['fld_name'],
                'fld_ord': row['model']['fld_ord'],
                'word_checked': row['word_check_btn'].isChecked(),
                'dict_name': row['dict_combo'].currentText().strip(),
                'dict_unique': row['dict_combo'].itemData(row['dict_combo'].currentIndex()),
                'dict_fld_name': row['field_combo'].currentText().strip(),
                'dict_fld_ord': row['field_combo'].itemData(row['field_combo'].currentIndex()),
                'ignore': row['ignore_check_btn'].isChecked(),
                'skip_valued': row['skip_check_btn'].isChecked(),
                'cloze_word': row['cloze_check_btn'].isChecked()
            })
            if 'prompt_edit' in row:
                maps[-1]['ai_prompt'] = row['prompt_edit'].toPlainText()
            if not maps[-1]['dict_unique']:
                maps[-1].update(dict_unique='', dict_name='', dict_fld_name='', dict_fld_ord=-1)
            saved = row.get('selected_mapping', row.get('saved_mapping', {}))
            if maps[-1]['dict_unique'] == saved.get('dict_unique'):
                if 'dict_name' in saved:
                    maps[-1]['dict_name'] = saved['dict_name']
                for key in ('dict_fld_name', 'dict_fld_ord'):
                    if key in saved:
                        maps[-1][key] = saved[key]
        return maps

    def commit_mapping(self):
        """Make a successful save the new baseline for later status-only refreshes."""
        self._conf = self.data or []
        for row, mapping in zip(self._options, self._conf):
            row['saved_mapping'] = dict(mapping)
            row['selected_mapping'] = dict(mapping)
            row['source_changed'] = row['field_changed'] = False
            row['dict_combo'].setProperty('fwq_saved_dictionary_name', mapping.get('dict_name') or mapping.get('dict_unique'))

    def ignore_all_check_changed(self):
        b = self.ignore_all_check_btn.isChecked()
        for row in self._options:
            row['ignore_check_btn'].setChecked(b)

    def skip_all_check_changed(self):
        b = self.skip_all_check_btn.isChecked()
        for row in self._options:
            row['skip_check_btn'].setChecked(b)

    def ignore_all_update(self):
        b = True
        for row in self._options:
            if not row['ignore_check_btn'].isChecked():
                b = False
                break
        self.ignore_all_check_btn.setChecked(b)

    def skip_all_update(self):
        b = True
        for row in self._options:
            if not row['skip_check_btn'].isChecked():
                b = False
                break
        self.skip_all_check_btn.setChecked(b)
