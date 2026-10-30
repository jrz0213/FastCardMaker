"""One dialog for destination fields, per-run AI settings and final review."""
from copy import deepcopy
from html import escape
from aqt import mw
from aqt.qt import *
from ..translations import text as tr
from ..service.ai_config import is_ai, profile_choices
from ..utils.media import profile_token
from ..service.note_placement import build_mappings
from .options_widgets import NoScrollComboBox


class NoteCreationDialog(QDialog):
    def __init__(self, owner, model, mappings):
        super().__init__(owner)
        self.owner, self.model = owner, model
        self.token = profile_token()
        self.cards = deepcopy([c for c in owner.cards if c['id'] not in owner.added_ids])
        self.busy = False
        self.setWindowTitle(tr('制卡配置与预览'))
        self.resize(1040, 740)
        self.setMinimumSize(780, 560)
        self.setObjectName('noteCreationDialog')
        self.setStyleSheet('''
            QDialog#noteCreationDialog QTabWidget::pane { border: 1px solid palette(mid); border-radius: 5px; }
            QDialog#noteCreationDialog QTabBar::tab { padding: 7px 18px; }
            QDialog#noteCreationDialog QPushButton { padding: 6px 16px; }
        ''')
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 10, 12, 12)
        self.main_layout.setSpacing(6)
        header_panel = QWidget()
        header = QGridLayout(header_panel)
        header.setContentsMargins(0, 0, 0, 0)
        header.setHorizontalSpacing(8)
        header.setVerticalSpacing(6)
        self.model_choice, self.mapping_choice, self.deck_choice = NoScrollComboBox(), NoScrollComboBox(), NoScrollComboBox()
        for item in mw.col.models.all():
            self.model_choice.addItem(item['name'], item['id'])
        from .configuration_style import style_note_types
        style_note_types(self.model_choice)
        self.model_choice.setCurrentIndex(self.model_choice.findData(model['id']))
        for col, (label, combo) in enumerate(((tr('笔记类型'), self.model_choice), (tr('字段配置'), self.mapping_choice), (tr('目标牌组'), self.deck_choice))):
            header.addWidget(QLabel(label + ":"), 0, col * 2)
            combo.setFixedHeight(32)
            combo.setMinimumWidth(0)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(12)
            header.addWidget(combo, 0, col * 2 + 1)
            header.setColumnStretch(col * 2 + 1, 1)
        self.main_layout.addWidget(header_panel)
        self.execution_mode = NoScrollComboBox()
        self.execution_mode.addItem(tr('仅调用 AI'), 'ai')
        self.execution_mode.addItem(tr('仅调用词典'), 'dictionary')
        self.execution_mode.addItem(tr('AI＋词典'), 'both')
        self.execution_mode.setFixedHeight(32)
        self.execution_mode.currentIndexChanged.connect(self.refresh_locks)
        self.editor = None
        self.last_deck = owner.deck.text()
        self.reload_decks(self.last_deck)
        self.deck_choice.activated.connect(self.choose_deck)
        self.model_choice.currentIndexChanged.connect(self.change_model)
        self.mapping_choice.currentIndexChanged.connect(self.change_mapping)
        self.change_model(initial_mapping=owner.mapping_combo.currentData())

    def change_model(self, *_args, initial_mapping=None):
        if self.busy:
            return
        from .type_query import configurations
        self.model = mw.col.models.get(self.model_choice.currentData())
        if self.model is None:
            return
        choices, default = configurations(self.model['id'])
        blocker = QSignalBlocker(self.mapping_choice)
        self.mapping_choice.clear()
        for i, value in enumerate(choices):
            self.mapping_choice.addItem(value.get('name', tr('配置 %s') % (i + 1)) if isinstance(value, dict) else tr('配置 %s') % (i + 1), i)
        if not choices:
            self.mapping_choice.addItem(tr('没有配置'), None)
        wanted = initial_mapping if initial_mapping is not None else default
        index = self.mapping_choice.findData(wanted)
        self.mapping_choice.setCurrentIndex(index if index >= 0 else 0)
        blocker.unblock()
        self.change_mapping()

    def change_mapping(self, *_):
        if self.busy:
            return
        from .type_query import configurations
        choices, _ = configurations(self.model['id'])
        index = self.mapping_choice.currentData()
        value = choices[index] if index is not None and 0 <= index < len(choices) else []
        mappings = value.get('fields', []) if isinstance(value, dict) else value
        self.owner.model_combo.setCurrentIndex(self.owner.model_combo.findData(self.model['id']))
        self.owner.mapping_combo.setCurrentIndex(self.owner.mapping_combo.findData(index))
        self.build_editor(mappings)

    def reload_decks(self, selected=''):
        blocker = QSignalBlocker(self.deck_choice)
        self.deck_choice.clear()
        for deck in sorted(mw.col.decks.all_names_and_ids(), key=lambda d: d.name):
            info = mw.col.decks.get(deck.id)
            if info and not info.get('dyn'):
                self.deck_choice.addItem(deck.name, deck.id)
        self.deck_choice.addItem(tr('＋新增牌组…'), None)
        index = self.deck_choice.findText(selected)
        self.deck_choice.setCurrentIndex(index if index >= 0 else (0 if self.deck_choice.count() > 1 else -1))
        if self.deck_choice.currentData() is not None:
            self.last_deck = self.deck_choice.currentText()
            self.owner.deck.setText(self.last_deck)
        blocker.unblock()

    def choose_deck(self, *_):
        if self.deck_choice.currentData() is None:
            name, ok = QInputDialog.getText(self, tr('新增牌组'), tr('牌组名称'))
            if not ok or not name.strip():
                self.reload_decks(self.last_deck)
                return
            try:
                did = mw.col.decks.id(name.strip())
                if mw.col.decks.get(did).get('dyn'):
                    raise ValueError('Filtered deck')
                self.reload_decks(name.strip())
            except Exception:
                QMessageBox.warning(self, tr('新增牌组'), tr('无法选择此牌组，请使用普通牌组。'))
                self.reload_decks(self.last_deck)
        else:
            self.last_deck = self.deck_choice.currentText()
            self.owner.deck.setText(self.last_deck)
        self.owner.save_draft()

    def build_editor(self, mappings):
        self.original_mappings = deepcopy(mappings)
        model, owner = self.model, self.owner
        self.fields = [f['name'] for f in model['flds']]
        self.notes = None
        if self.editor is not None:
            self.main_layout.removeWidget(self.editor)
            self.editor.deleteLater()
        self.editor = QWidget()
        self.main_layout.addWidget(self.editor, 1)
        layout = QVBoxLayout(self.editor)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        destination_panel = QWidget()
        form = QGridLayout(destination_panel)
        form.setContentsMargins(0, 0, 0, 0)
        form.setHorizontalSpacing(8)
        form.setVerticalSpacing(6)
        self.title_target, self.content_target = NoScrollComboBox(), NoScrollComboBox()
        saved = owner.field_positions.get(str(model['id']), {})
        for combo, key, default in ((self.title_target, 'title', 0), (self.content_target, 'content', min(1, len(self.fields) - 1))):
            combo.addItems(self.fields)
            index = combo.findText(saved.get(key, ''))
            combo.setCurrentIndex(index if index >= 0 else default)
        qa = owner.creation_mode.currentData() == 'qa'
        for col, (label, combo) in enumerate(((tr('问题存入') if qa else tr('标题存入'), self.title_target),
                                             (tr('答案存入') if qa else tr('内容存入'), self.content_target),
                                             (tr('执行模式'), self.execution_mode))):
            form.addWidget(QLabel(label + ":"), 0, col * 2)
            combo.setFixedHeight(32)
            combo.setMinimumWidth(0)
            form.addWidget(combo, 0, col * 2 + 1)
            form.setColumnStretch(col * 2 + 1, 1)
        layout.addWidget(destination_panel)
        note = QLabel(tr('填入字段不重复查询；灰色行本次不执行。此处修改仅用于本次制卡。'))
        note.setWordWrap(True)
        note.setForegroundRole(QPalette.ColorRole.PlaceholderText)
        layout.addWidget(note)
        self.tabs = QTabWidget()
        self.tabs.setObjectName('noteCreationTabs')
        self.tabs.setStyleSheet('QTabWidget#noteCreationTabs::tab-bar { alignment: left; }')
        self.tabs.tabBar().setExpanding(False)
        self.tabs.setDocumentMode(True)
        layout.addWidget(self.tabs, 1)
        self.table = QTableWidget(len(self.fields), 3)
        self.table.setHorizontalHeaderLabels([tr('字段'), tr('内容来源（AI / 词典）'), tr('数据项 / 提示词')])
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setAlternatingRowColors(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 165)
        self.table.setColumnWidth(1, 200)
        self.table.setStyleSheet('QTableWidget::item { padding: 6px 12px; border-bottom: 1px solid palette(mid); }')
        self.table.horizontalHeader().setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.tabs.addTab(self.table, tr('字段配置'))
        self.preview = QTreeWidget()
        self.preview.setHeaderLabels([tr('字段'), tr('内容')])
        self.preview.setWordWrap(True)
        self.preview.setColumnWidth(0, 240)
        self.preview.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.preview.setStyleSheet('QTreeWidget::item { padding: 7px 10px; }')
        self.tabs.addTab(self.preview, tr('笔记预览'))
        self.rows = []
        self.row_views = []
        choices = profile_choices()
        for i, name in enumerate(self.fields):
            original = next((m for j, m in enumerate(mappings) if (m.get('fld_name') or (self.fields[j] if j < len(self.fields) else '')) == name), {})
            self.table.setItem(i, 0, QTableWidgetItem(name))
            self.table.item(i, 0).setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
            combo = NoScrollComboBox()
            combo.addItem(tr('不处理'), '')
            for choice in choices:
                combo.addItem(choice['title'], choice['unique'])
            unique = original.get('dict_unique', '')
            if unique and not is_ai(unique):
                combo.addItem(original.get('dict_name') or str(unique), unique)
            if is_ai(unique) and combo.findData(unique) < 0:
                combo.addItem(tr('原 AI 配置不可用'), unique)
            if not original.get('ignore', False) and unique:
                combo.setCurrentIndex(max(0, combo.findData(unique)))
            prompt = QPlainTextEdit(original.get('ai_prompt', ''))
            combo.setFixedHeight(32)
            combo.setMinimumWidth(0)
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(14)
            prompt.setMaximumHeight(52)
            prompt.setFrameShape(QFrame.Shape.NoFrame)
            prompt.setStyleSheet('QPlainTextEdit { padding: 5px 8px; border: 1px solid palette(mid); border-radius: 5px; }')
            prompt.setMinimumHeight(0)
            prompt.setPlaceholderText(tr('填写本字段的生成要求'))
            choice_view, prompt_view = QStackedWidget(), QStackedWidget()
            for view in (choice_view, prompt_view):
                view.setMinimumHeight(0)
                view.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Ignored)
            combo_cell = QWidget()
            cell_layout = QHBoxLayout(combo_cell)
            cell_layout.setContentsMargins(6, 4, 6, 4)
            cell_layout.addWidget(combo, 1, Qt.AlignmentFlag.AlignVCenter)
            role_label, hint = QLabel(), QLabel()
            for label in (role_label, hint):
                label.setWordWrap(True)
                label.setMargin(8)
                label.setTextFormat(Qt.TextFormat.PlainText)
            choice_view.addWidget(combo_cell)
            choice_view.addWidget(role_label)
            prompt_cell = QWidget()
            prompt_layout = QHBoxLayout(prompt_cell)
            prompt_layout.setContentsMargins(8, 4, 8, 4)
            prompt_layout.addWidget(prompt)
            prompt_view.addWidget(prompt_cell)
            prompt_view.addWidget(hint)
            self.table.setCellWidget(i, 1, choice_view)
            self.table.setCellWidget(i, 2, prompt_view)
            self.row_views.append((choice_view, prompt_view, role_label, hint))
            self.rows.append((name, combo, prompt))
            combo.currentIndexChanged.connect(self.refresh_locks)
            prompt.textChanged.connect(self.invalidate)
        self.title_target.currentIndexChanged.connect(self.refresh_locks)
        self.content_target.currentIndexChanged.connect(self.refresh_locks)
        self.status = QLabel('')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        buttons = QHBoxLayout()
        summary = QLabel(tr('共 %s 条笔记') % len(self.cards))
        buttons.addWidget(summary)
        buttons.addStretch()
        self.generate = QPushButton(tr('生成预览'))
        self.add = QPushButton(tr('确认添加'))
        self.add.setEnabled(False)
        cancel = QPushButton(tr('关闭'))
        for button in (cancel, self.generate, self.add):
            button.setMinimumHeight(34)
            button.setMinimumWidth(110)
            buttons.addWidget(button)
        self.add.setDefault(True)
        layout.addLayout(buttons)
        self.generate.clicked.connect(self.make_preview)
        self.add.clicked.connect(self.add_notes)
        cancel.clicked.connect(self.reject)
        self.refresh_locks()

    def invalidate(self, *_):
        self.notes = None
        self.add.setEnabled(False)
        self.preview.clear()

    def refresh_locks(self, *_):
        if not hasattr(self, 'rows'):
            return
        title, content = self.title_target.currentText(), self.content_target.currentText()
        locked = {title, content}
        qa = self.owner.creation_mode.currentData() == 'qa'
        for i, (name, combo, prompt) in enumerate(self.rows):
            combo.setEnabled(name not in locked)
            unique = combo.currentData()
            is_dictionary = bool(unique) and not is_ai(unique)
            mode = self.execution_mode.currentData()
            skipped = bool(unique) and ((mode == 'ai' and is_dictionary) or (mode == 'dictionary' and is_ai(unique)))
            active_ai = name not in locked and bool(unique) and not skipped and not is_dictionary
            prompt.setEnabled(active_ai)
            choice_view, prompt_view, role_label, hint = self.row_views[i]
            choice_view.setCurrentIndex(1 if name in locked else 0)
            prompt_view.setCurrentIndex(0 if active_ai else 1)
            muted = self.table.palette().color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
            base = self.table.palette().color(QPalette.ColorRole.Base)
            tint = QColor((base.red() * 9 + muted.red()) // 10,
                          (base.green() * 9 + muted.green()) // 10,
                          (base.blue() * 9 + muted.blue()) // 10)
            dimmed = skipped and name not in locked
            field_item = self.table.item(i, 0)
            field_item.setForeground(QBrush(muted) if dimmed else QBrush())
            field_item.setBackground(QBrush(tint) if dimmed else QBrush())
            for view in (choice_view, prompt_view):
                view.setStyleSheet('QStackedWidget { background-color: %s; }' % tint.name() if dimmed else '')
            combo.setStyleSheet('QComboBox { color: %s; }' % muted.name() if dimmed else '')
            hint.setStyleSheet('color: %s;' % muted.name() if dimmed else '')
            for option in range(combo.count()):
                value = combo.itemData(option)
                excluded = bool(value) and ((mode == 'ai' and not is_ai(value)) or (mode == 'dictionary' and is_ai(value)))
                combo.setItemData(option, QBrush(muted) if excluded else None, Qt.ItemDataRole.ForegroundRole)
            if name in locked:
                if title == content:
                    role = tr('填入问题＋答案') if qa else tr('填入主题＋内容')
                elif name == title:
                    role = tr('填入问题') if qa else tr('填入主题')
                else:
                    role = tr('填入答案') if qa else tr('填入内容')
                role_label.setText(role)
                hint.setText(tr('直接填入，不调用 AI 或词典'))
            else:
                if skipped:
                    hint.setText(tr('当前模式不执行此来源'))
                elif is_dictionary:
                    original = next((m for j, m in enumerate(self.original_mappings) if (m.get('fld_name') or (self.fields[j] if j < len(self.fields) else '')) == name), {})
                    hint.setText(tr('词典数据项：') + str(original.get('dict_fld_name', '')))
                else:
                    hint.setText(tr('此字段留空'))
            self.table.item(i, 0).setText(name)
            self.table.setRowHeight(i, 62)
        self.invalidate()

    def make_preview(self):
        if self.busy or self.token != profile_token():
            return
        self.invalidate()
        from ..query.ai_runner import AIQueryRunner
        source, content = self.title_target.currentText(), self.content_target.currentText()
        mappings = build_mappings([(name, combo.currentData(), prompt.toPlainText())
                                   for name, combo, prompt in self.rows], source, content,
                                  tr('结合以下内容按本字段格式生成：'), self.execution_mode.currentData())
        for mapping in mappings:
            if mapping['dict_unique'] and not is_ai(mapping['dict_unique']):
                original = next((m for j, m in enumerate(self.original_mappings) if (m.get('fld_name') or (self.fields[j] if j < len(self.fields) else '')) == mapping['fld_name']), {})
                for key in ('dict_name', 'dict_fld_name', 'dict_fld_ord', 'cloze_word'):
                    if key in original:
                        mapping[key] = deepcopy(original[key])
        notes = []
        for card in self.cards:
            note = mw.col.new_note(self.model)
            note[source] = escape(card['topic']).replace('\n', '<br>')
            body = escape(card['content']).replace('\n', '<br>')
            if source == content:
                note[source] += '<br>' + body
            else:
                note[content] = body
            notes.append(note)
        if not notes:
            return
        self.busy = True
        self.setEnabled(False)
        try:
            if any(not m['ignore'] and m['dict_unique'] and not is_ai(m['dict_unique']) for m in mappings):
                from ..query.worker import QueryWorkerManager
                dictionary = QueryWorkerManager()
                dictionary.flush = False
                dictionary.include_ai = False
                dictionary.query_mappings = mappings
                for note in notes:
                    dictionary.queue.put(note)
                dictionary.start()
                dictionary.join()
                if dictionary.errors or dictionary.fails or dictionary.cancelled or self.token != profile_token():
                    self.status.setText(tr('生成失败或已取消，尚未添加笔记，可重试。'))
                    return
            runner = AIQueryRunner(notes, mappings=mappings, model=self.model, flush=False)
            if runner.validation_errors:
                self.status.setText('\n'.join(runner.validation_errors))
                return
            if runner.tasks:
                runner.run(parent=self, report=False)
            if runner.failed or runner.was_cancelled or self.token != profile_token():
                self.status.setText(tr('生成失败或已取消，尚未添加笔记，可重试。'))
                return
            self.notes = notes
            for card, note in zip(self.cards, notes):
                root = QTreeWidgetItem(self.preview, [card['topic'], ''])
                for name in self.fields:
                    QTreeWidgetItem(root, [name, note[name]])
            self.preview.expandAll()
            self.tabs.setCurrentIndex(1)
            self.add.setEnabled(True)
            self.owner.field_positions[str(self.model['id'])] = {'title': source, 'content': content}
            self.owner.save_draft()
        finally:
            self.busy = False
            self.setEnabled(True)

    def add_notes(self):
        if self.busy or not self.notes or self.token != profile_token():
            return
        undo = mw.col.add_custom_undo_entry(tr('AI 批量制卡'))
        try:
            did = self.deck_choice.currentData()
            deck = mw.col.decks.get(did) if did is not None else None
            if not deck or deck.get('dyn'):
                self.status.setText(tr('请选择普通目标牌组。'))
                return
            while self.notes:
                card, note = self.cards[0], self.notes[0]
                mw.col.add_note(note, did)
                self.owner.added_ids.add(card['id'])
                self.owner.cards = [c for c in self.owner.cards if c['id'] != card['id']]
                self.notes.pop(0)
                self.cards.pop(0)
                self.owner.save_draft()
            mw.reset()
            self.owner.render_cards(self.owner.cards)
            self.owner.save.setEnabled(bool(self.owner.cards))
            self.owner.status.setText(tr('已按字段配置生成并添加到 Anki，可撤销。'))
            self.accept()
        except Exception:
            self.status.setText(tr('操作中断，未添加的主题已保留。'))
        finally:
            mw.col.merge_undo_entries(undo)

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            super().closeEvent(event)

    def reject(self):
        if not self.busy:
            super().reject()
