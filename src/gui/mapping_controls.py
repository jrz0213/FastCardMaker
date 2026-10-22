"""Build mapping rows and populate dictionary and exported-field choices."""

from aqt.qt import *
import re
from ..translations import text as tr

from ..lang import _, _sl
from .base import WIDGET_SIZE
from .options_widgets import NoScrollComboBox
from .ai_mapping import prompt_controls
from ..service.ai_config import is_ai

def add_dict_layout(self, i, **kwargs):
    word_checked = kwargs.get('word_checked', False)
    fld_name, fld_ord = kwargs.get('fld_name', ''), kwargs.get('fld_ord', '')
    dict_name, dict_unique, dict_fld_name, dict_fld_ord = (
        kwargs.get('dict_name', ''), kwargs.get('dict_unique', ''),
        kwargs.get('dict_fld_name', ''), kwargs.get('dict_fld_ord', 0)
    )
    ignore, skip, cloze = kwargs.get('ignore', True), kwargs.get('skip_valued', True), kwargs.get('cloze_word', False)

    word_check_btn = QRadioButton(fld_name)
    word_check_btn.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
    word_check_btn.setCheckable(True)
    word_check_btn.setChecked(word_checked)
    word_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.radio_group.addButton(word_check_btn)

    combo_style = """
            QComboBox {
                padding: 4px;
                border: 1px solid rgba(128, 128, 128, 0.4);
                border-radius: 4px;
            }
        """

    dict_combo = NoScrollComboBox()
    dict_combo.setProperty('fwq_saved_dictionary_name', dict_name or dict_unique)
    dict_combo.setStyleSheet(combo_style)
    dict_combo.setMinimumSize(WIDGET_SIZE.map_dict_width, 24)
    dict_combo.setFocusPolicy(Qt.FocusPolicy.TabFocus | Qt.FocusPolicy.ClickFocus | Qt.FocusPolicy.StrongFocus)
    ignore = not self.fill_dict_combo_options(dict_combo, dict_unique, self._services) or ignore
    dict_unique = dict_combo.itemData(dict_combo.currentIndex())
    dict_combo.setEnabled(not word_checked and not ignore)

    field_combo = NoScrollComboBox()
    field_combo.setStyleSheet(combo_style)
    field_combo.setMinimumSize(WIDGET_SIZE.map_field_width, 24)
    field_combo.setFocusPolicy(Qt.FocusPolicy.TabFocus | Qt.FocusPolicy.ClickFocus | Qt.FocusPolicy.StrongFocus)
    field_combo.setEnabled(not word_checked and not ignore)
    self.fill_field_combo_options(field_combo, dict_name, dict_unique, dict_fld_name, dict_fld_ord)
    data_widget, prompt_edit, refresh_prompt = prompt_controls(
        dict_combo, field_combo, kwargs.get('ai_prompt', ''), self)

    ignore_check_btn = QCheckBox(_("NOT_DICT_FIELD"))
    ignore_check_btn.setEnabled(not word_checked)
    ignore_check_btn.setChecked(ignore)
    ignore_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    skip_check_btn = QCheckBox(_("SKIP_VALUED"))
    skip_check_btn.setEnabled(not word_checked and not ignore)
    skip_check_btn.setChecked(skip)
    skip_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    cloze_check_btn = QCheckBox(_("CLOZE_WORD"))
    cloze_check_btn.setEnabled(not word_checked and not ignore)
    cloze_check_btn.setChecked(cloze)
    cloze_check_btn.setCursor(Qt.CursorShape.PointingHandCursor)

    def radio_btn_checked():
        if self._last_checkeds:
            self._last_checkeds[0].setEnabled(True)
            ignore = self._last_checkeds[0].isChecked()
            for k in range(1, len(self._last_checkeds)):
                self._last_checkeds[k].setEnabled(not ignore)

        is_word = word_check_btn.isChecked()
        ignore_check_btn.setEnabled(not is_word)
        curr_ignore = ignore_check_btn.isChecked()

        dict_combo.setEnabled(not is_word and not curr_ignore)
        field_combo.setEnabled(not is_word and not curr_ignore)
        skip_check_btn.setEnabled(not is_word and not curr_ignore)
        cloze_check_btn.setEnabled(not is_word and not curr_ignore)
        refresh_prompt()

        if is_word:
            self._last_checkeds = [ignore_check_btn, dict_combo, field_combo, skip_check_btn, cloze_check_btn, prompt_edit]

    word_check_btn.clicked.connect(radio_btn_checked)
    if word_checked:
        self._last_checkeds = None
        radio_btn_checked()

    def ignore_check_changed():
        is_word = word_check_btn.isChecked()
        curr_ignore = ignore_check_btn.isChecked()
        dict_combo.setEnabled(not is_word and not curr_ignore)
        field_combo.setEnabled(not is_word and not curr_ignore)
        skip_check_btn.setEnabled(not is_word and not curr_ignore)
        cloze_check_btn.setEnabled(not is_word and not curr_ignore)
        refresh_prompt()

    ignore_check_btn.stateChanged.connect(ignore_check_changed)
    ignore_check_btn.clicked.connect(self.ignore_all_update)
    skip_check_btn.clicked.connect(self.skip_all_update)

    def dict_combo_changed(index):
        self.fill_field_combo_options(
            field_combo, dict_combo.currentText(),
            dict_combo.itemData(index), field_combo.currentText(),
            field_combo.itemData(field_combo.currentIndex()), allow_default=False)
        refresh_prompt()

    dict_combo.currentIndexChanged.connect(dict_combo_changed)

    def mark_local_dirty(*args):
        if not self._is_building and self._parent_dialog and hasattr(self._parent_dialog, '_is_dirty'):
            self._parent_dialog._is_dirty = True

    word_check_btn.clicked.connect(mark_local_dirty)
    ignore_check_btn.stateChanged.connect(mark_local_dirty)
    skip_check_btn.stateChanged.connect(mark_local_dirty)
    cloze_check_btn.stateChanged.connect(mark_local_dirty)
    dict_combo.currentIndexChanged.connect(mark_local_dirty)
    field_combo.currentIndexChanged.connect(mark_local_dirty)

    row_idx = i + 1
    self.dicts_layout.addWidget(word_check_btn, row_idx, 0)
    self.dicts_layout.addWidget(ignore_check_btn, row_idx, 1)
    self.dicts_layout.addWidget(dict_combo, row_idx, 2)
    self.dicts_layout.addWidget(data_widget, row_idx, 3)
    self.dicts_layout.addWidget(skip_check_btn, row_idx, 4)
    self.dicts_layout.addWidget(cloze_check_btn, row_idx, 5)

    row = {
        'saved_mapping': dict(kwargs),
        'selected_mapping': dict(kwargs),
        'source_changed': False,
        'field_changed': False,
        'model': {'fld_name': fld_name, 'fld_ord': fld_ord},
        'word_check_btn': word_check_btn,
        'dict_combo': dict_combo,
        'field_combo': field_combo,
        'prompt_edit': prompt_edit,
        'refresh_prompt': refresh_prompt,
        'ignore_check_btn': ignore_check_btn,
        'skip_check_btn': skip_check_btn,
        'cloze_check_btn': cloze_check_btn
    }
    self._options.append(row)
    def source_exists(unique):
        return any(item['unique'] == unique for kind in ('local', 'web', 'ai')
                   for item in self._services.get(kind, []))
    def capture_source(*_):
        unique = dict_combo.currentData()
        if unique and not source_exists(unique):
            return
        row['source_changed'] = True
        row['selected_mapping'].update(dict_unique=unique or '',
            dict_name=dict_combo.currentText().strip() if unique else '',
            dict_fld_name=field_combo.currentText().strip() if unique else '',
            dict_fld_ord=field_combo.currentData() if unique else -1)
        dict_combo.setProperty('fwq_saved_dictionary_name', row['selected_mapping']['dict_name'])
    def capture_field(*_):
        unique = dict_combo.currentData()
        if not source_exists(unique) or (field_combo.currentData() is None and not field_combo.isEditable()):
            return
        row['field_changed'] = True
        row['selected_mapping'].update(dict_fld_name=field_combo.currentText().strip(),
                                       dict_fld_ord=field_combo.currentData())
    dict_combo.currentIndexChanged.connect(capture_source)
    field_combo.currentIndexChanged.connect(capture_field)
    field_combo.editTextChanged.connect(capture_field)

def fill_dict_combo_options(self, dict_combo, current_unique, services):
    from ..service import service_manager
    aliases = getattr(service_manager, 'aliases', {})
    if isinstance(aliases, dict):
        current_unique = aliases.get(current_unique, current_unique)
    dict_combo.clear()
    font = dict_combo.font()
    font.setStrikeOut(False)
    dict_combo.setFont(font)
    if not current_unique:
        dict_combo.addItem(tr('未选择来源'), userData=None)

    def unavailable():
        saved = dict_combo.property('fwq_saved_dictionary_name')
        title = saved if isinstance(saved, str) and saved else str(current_unique or '')
        title = re.sub(r'^[🌐🟢⚪🔴🤖\s]+', '', title or '')
        dict_combo.addItem(title, userData=current_unique)
        item = dict_combo.model().item(dict_combo.count() - 1)
        if item:
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            font = item.font()
            font.setStrikeOut(True)
            item.setFont(font)
        font = dict_combo.font()
        font.setStrikeOut(True)
        dict_combo.setFont(font)

    ai_services = services.get('ai', [])
    for service in ai_services:
        dict_combo.addItem(service['title'], userData=service['unique'])
    if is_ai(current_unique) and not any(item['unique'] == current_unique for item in ai_services):
        unavailable()
    if dict_combo.count() and (services['local'] or services['web']):
        dict_combo.insertSeparator(dict_combo.count())

    for service in services['local']:
        status = service.get('status', 'uninitialized')
        title = service.get('title', 'Unknown')
        is_selectable = True

        if status == 'building':
            display_title = title + tr(' (建库中)')
            is_selectable = False
        elif status == 'checking':
            display_title = title + tr(' (状态检测)')
            is_selectable = False
        elif status == 'ready':
            display_title = title
        elif status == 'failed':
            display_title = title + tr(' (初始化失败，可重试)')
            is_selectable = False
        else:
            display_title = title + tr(' (未就绪)')
            is_selectable = False

        dict_combo.addItem(display_title, userData=service['unique'])

        if not is_selectable:
            index = dict_combo.count() - 1
            model = dict_combo.model()
            item = model.item(index)
            if item:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)

    if len(services['local']) > 0:
        dict_combo.insertSeparator(dict_combo.count())

    for service in services['web']:
        dict_combo.addItem(service['title'], userData=service['unique'])

    known = {service['unique'] for service in services['local'] + services['web'] + ai_services}
    if current_unique and not is_ai(current_unique) and current_unique not in known:
        unavailable()

    def set_dict_combo_index():
        dict_combo.setCurrentIndex(0)
        if current_unique:
            for i in range(dict_combo.count()):
                if dict_combo.itemData(i) == current_unique:
                    dict_combo.setCurrentIndex(i)
                    dict_combo.setToolTip(dict_combo.currentText())
                    return True
        return False

    result = set_dict_combo_index()
    def update_font(*_):
        item = dict_combo.model().item(dict_combo.currentIndex())
        font = dict_combo.font()
        font.setStrikeOut(bool(item and item.font().strikeOut()))
        dict_combo.setFont(font)
    if not dict_combo.property('fwq_strike_connected'):
        dict_combo.currentIndexChanged.connect(update_font)
        dict_combo.setProperty('fwq_strike_connected', True)
    update_font()
    return result

def fill_field_combo_options(self, field_combo, dict_combo_text,
                             dict_combo_itemdata, dict_fld_name,
                             dict_fld_ord, allow_default=False):
    field_combo.clear()
    field_combo.setEditable(False)
    if is_ai(dict_combo_itemdata):
        field_combo.addItem(tr('AI 回复'), userData=0)
        return
    if dict_combo_text in _sl('MDX_SERVER'):
        text = dict_fld_name if dict_fld_name else 'http://'
        field_combo.setEditable(True)
        field_combo.setEditText(text)
        field_combo.setFocus(Qt.FocusReason.MouseFocusReason)
    else:
        unique = dict_combo_itemdata
        fields = self._controller.get_service_fields(unique)
        field_combo.setCurrentIndex(0)
        for i, each in enumerate(fields):
            field_combo.addItem(each, userData=i)
        valid_order = type(dict_fld_ord) is int and 0 <= dict_fld_ord < len(fields)
        name_matches = any(each == dict_fld_name for each in fields)
        if fields and (name_matches or not dict_fld_name and valid_order or allow_default):
            selected = next((i for i, each in enumerate(fields) if each == dict_fld_name), None)
            if selected is None:
                selected = dict_fld_ord if valid_order else 0
            field_combo.setCurrentIndex(selected)
        elif unique:
            field_combo.addItem(tr('不可用'), userData=-1)
            field_combo.setToolTip(dict_fld_name or str(dict_fld_ord))
            index = field_combo.count() - 1
            item = field_combo.model().item(index)
            if item:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            field_combo.setCurrentIndex(index)
