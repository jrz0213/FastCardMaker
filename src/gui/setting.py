# -*- coding:utf-8 -*-
"""Small settings tabs; global AI styling is applied by successful query writes."""
from copy import deepcopy
import json
from pathlib import Path
from aqt import mw
from aqt.qt import *
from ..context import config
from ..lang import _
from ..translations import text as tr
from ..i18n import languages
from ..utils.ai_format import DEFAULT_CSS, global_css, rules
from .base import Dialog
from .help_widgets import with_help
from ..service.ai_config import ai_send_rate, transport_settings, save_transport


class SettingDialog(Dialog):
    def __init__(self, parent, title=None):
        super().__init__(parent, title or _('SETTINGS'))
        self.resize(700, 650)
        outer = QVBoxLayout(self)
        tabs = self.settings_tabs = QTabWidget()
        outer.addWidget(tabs)
        general = QWidget()
        general_layout = QVBoxLayout(general)
        self.language_combo = QComboBox()
        self.language_combo.addItem(tr('跟随 Anki'), '')
        for code, name in languages():
            self.language_combo.addItem(name, code)
        self.language_combo.setCurrentIndex(max(0, self.language_combo.findData(getattr(config, 'ui_language', ''))))
        form = QFormLayout()
        self.ai_send_mode = QComboBox()
        self.ai_send_mode.addItem(tr('每张卡片一次发送（默认）'), 'note')
        self.ai_send_mode.addItem(tr('每个字段分别发送'), 'field')
        self.ai_send_mode.setCurrentIndex(max(0, self.ai_send_mode.findData(getattr(config, 'ai_send_mode', 'note'))))
        form.addRow(tr('AI 发送方式'), with_help(self.ai_send_mode, tr('AI 发送方式'), tr(
            '按笔记发送：同一笔记使用同一 AI 连接的字段合并请求，减少重复输入。逐字段发送：每个目标字段单独请求。'
            '字段提示词支持多个 {{字段名}}；切换 AI 连接不会改写提示词。')))
        general_layout.addLayout(form)
        transport = transport_settings()
        for attr, label, low, high, value in (
            ('ai_rate', tr('每分钟发送数（全局）'), 1, 600, ai_send_rate()),
            ('ai_timeout', tr('请求超时'), 1, 600, transport['timeout']),
            ('ai_connect_timeout', tr('连接超时'), 1, 60, transport['connect_timeout']),
            ('ai_retries', tr('自动重试次数'), 0, 5, transport['retries'])):
            control = QSpinBox()
            control.setRange(low, high)
            control.setValue(value)
            if attr in ('ai_timeout', 'ai_connect_timeout'):
                control.setSuffix(tr(' 秒'))
            elif attr == 'ai_rate':
                control.setSuffix(tr(' 次/分钟'))
            setattr(self, attr, control)
            if attr == 'ai_retries':
                control = with_help(control, tr('请求参数'), tr(
                    '每分钟发送数：所有 AI 连接共用，按间隔平滑发送，未发送的请求排队等待。\n\n'
                    '连接超时：建立网络连接最多等待多久。请求超时：等待服务响应的超时设置。\n\n'
                    '自动重试：限流和临时服务错误时额外尝试的次数，0 表示不重试；密钥或参数错误不重试，网络超时不会盲目重发。'))
            form.addRow(label, control)
        self.ai_markdown = QCheckBox(tr('解析 Markdown（标题、表格、列表等）'))
        self.ai_markdown.setChecked(bool(getattr(config, 'ai_markdown', True)))
        general_layout.addWidget(self.ai_markdown)
        self.ai_css_enabled = QCheckBox(tr('启用 CSS 注入（默认关闭）'))
        self.ai_css_enabled.setChecked(bool(getattr(config, 'ai_css_enabled', False)))
        general_layout.addWidget(with_help(self.ai_css_enabled, tr('内容格式与 CSS'), tr(
            'Markdown 将标题、表格和列表等内容转换为卡片可显示的 HTML。CSS 注入默认关闭，重点美化表格。\n\n'
            '全局 CSS 由勾选的笔记类型共用，类型默认全选，可按需取消；只有运行时实际成功写入笔记，才向该类型注入样式。'
            '只保存设置或查询未产生修改时不会注入。只更新插件标记的区块，保留其他 CSS，相同内容不重复插入。')))
        self.css_toggle = QToolButton()
        self.css_toggle.setText(tr('查看／编辑全局 CSS'))
        self.css_toggle.setCheckable(True)
        self.css_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.css_toggle.setArrowType(Qt.ArrowType.RightArrow)
        general_layout.addWidget(self.css_toggle)
        panel = self.css_panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.addWidget(QLabel(tr('生效的笔记类型')))
        self.style_types = QListWidget()
        self.style_types.setStyleSheet('QListWidget::item { padding-left: 8px; }')
        self.style_types.setMaximumHeight(95)
        styles = getattr(config, 'ai_styles', {})
        styles = styles if isinstance(styles, dict) else {}
        for model in mw.col.models.all():
            item = QListWidgetItem(model['name'], self.style_types)
            item.setData(Qt.ItemDataRole.UserRole, model['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if styles.get(str(model['id']), {}).get('enabled', True) else Qt.CheckState.Unchecked)
        general_layout.addWidget(self.style_types)
        self.style_css = QPlainTextEdit(global_css(config))
        self.style_css.setMinimumHeight(125)
        panel_layout.addWidget(self.style_css)
        panel.hide()
        self.css_toggle.toggled.connect(self._toggle_css)
        general_layout.addWidget(panel)
        general_layout.addStretch()
        def add_page(widget, title):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setWidget(widget)
            tabs.addTab(scroll, title)
        add_page(general, tr('AI 设置'))

        automatic = QWidget()
        auto_layout = QVBoxLayout(automatic)
        language_form = QFormLayout()
        language_form.addRow(tr('界面语言'), with_help(self.language_combo, tr('界面语言'), tr('保存后重新打开窗口以应用语言。')))
        auto_layout.addLayout(language_form)
        settings = getattr(config, 'auto_run', {})
        settings = settings if isinstance(settings, dict) else {}
        self.auto_enabled = QCheckBox(tr('启用定时制作'))
        self.auto_enabled.setChecked(bool(settings.get('enabled', False)))
        auto_layout.addWidget(with_help(self.auto_enabled, tr('定时制作'), tr(
            '只处理启用后新增笔记的空字段，使用对应类型的星标配置；没有有效星标时使用首份配置。'
            '只检查勾选的类型，上一批未结束时跳过本轮，Anki 关闭后停止。\n\n'
            '倒计时提示出现后可取消本轮，未操作则自动开始。此功能不会扫描并重做所有旧笔记。')))
        self.auto_panel = QWidget()
        schedule_layout = QVBoxLayout(self.auto_panel)
        schedule_layout.setContentsMargins(8, 0, 0, 0)
        interval = QHBoxLayout()
        interval.addWidget(QLabel(tr('检测间隔（分钟）')))
        self.auto_interval = QSpinBox()
        self.auto_interval.setRange(1, 1440)
        self.auto_interval.setValue(settings.get('interval_minutes', 5))
        interval.addWidget(self.auto_interval)
        schedule_layout.addLayout(interval)
        self.auto_models = QListWidget()
        self.auto_models.setStyleSheet('QListWidget::item { padding-left: 8px; }')
        self.auto_models.setMaximumHeight(160)
        selected = {str(v) for v in settings.get('model_ids', [])}
        for model in mw.col.models.all():
            conf = getattr(config, 'get_maps', lambda mid: {})(model['id'])
            choices = conf.get('list', []) if isinstance(conf, dict) else []
            index = conf.get('auto', 0) if isinstance(conf, dict) else 0
            index = index if type(index) is int and 0 <= index < len(choices) else 0
            choice = choices[index] if choices else {}
            name = choice.get('name', tr('配置 %s') % 1) if isinstance(choice, dict) else tr('配置 %s') % 1
            item = QListWidgetItem(model['name'] + ' · ' + name, self.auto_models)
            item.setData(Qt.ItemDataRole.UserRole, model['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if str(model['id']) in selected else Qt.CheckState.Unchecked)
        schedule_layout.addWidget(QLabel(tr('勾选参与自动制作的笔记类型')))
        select = self.auto_select_all = QCheckBox(tr('全选／取消全选'))
        select.setTristate(True)
        select.setProperty('fastcm_ephemeral', True)
        select.clicked.connect(lambda checked: [self.auto_models.item(i).setCheckState(
            Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked) for i in range(self.auto_models.count())])
        def refresh_selection(*_):
            count = sum(self.auto_models.item(i).checkState() == Qt.CheckState.Checked for i in range(self.auto_models.count()))
            select.blockSignals(True)
            select.setCheckState(Qt.CheckState.Checked if count and count == self.auto_models.count() else
                                 Qt.CheckState.PartiallyChecked if count else Qt.CheckState.Unchecked)
            select.blockSignals(False)
        self.auto_models.itemChanged.connect(refresh_selection)
        refresh_selection()
        schedule_layout.addWidget(select)
        schedule_layout.addWidget(self.auto_models)
        self.auto_panel.setVisible(self.auto_enabled.isChecked())
        self.auto_panel.setEnabled(self.auto_enabled.isChecked())
        self.auto_enabled.toggled.connect(self.auto_panel.setVisible)
        self.auto_enabled.toggled.connect(self.auto_panel.setEnabled)
        auto_layout.addWidget(self.auto_panel)
        self.configuration_loaded = False
        from .backup_controls import build_controls
        build_controls(self, auto_layout)
        auto_layout.addStretch()
        add_page(automatic, tr('通用设置'))

        advanced = QWidget()
        advanced_layout = QFormLayout(advanced)
        advanced_layout.addRow(with_help(QLabel(tr('词典查询')), tr('词典查询'), tr(
            '强制更新字段：允许空查询结果清空目标字段；不勾选时保留原内容。是否查询已有内容仍由字段映射中的“跳过有值项”控制。'
            '忽略声调：查询前去掉重音标记。忽略大小写：本地词典查找不区分大小写。\n\n'
            '线程数控制词典查询并行量，不改变 AI 的每分钟发送数。媒体模糊匹配用于严格路径未找到时尝试相近资源名，可能匹配到同名资源。'
            '音频缺失时先确认 MDD／资源完整，再尝试发送 HTML、JS 和原脚本让 AI 检查路径。\n\n'
            '单词填空格式中的 %s 表示单词；音频格式中的 {0} 表示媒体文件名。修改格式前保留对应占位符。')))
        for attr, label, key, default in (
            ('check_force_update', _('FORCE_UPDATE'), 'force_update', False),
            ('check_ignore_accents', _('IGNORE_ACCENTS'), 'ignore_accents', False),
            ('check_ighore_mdx_wordcase', _('IGNORE_MDX_WORDCASE'), 'ignore_mdx_wordcase', False),
            ('check_fuzzy_match', tr('媒体资源模糊匹配 (Fuzzy Match)'), 'fuzzy_match', True)):
            box = QCheckBox(label)
            box.setChecked(bool(getattr(config, key, default)))
            setattr(self, attr, box)
            advanced_layout.addRow(box)
        self.input_thread_number = QSpinBox()
        self.input_thread_number.setRange(1, 120)
        self.input_thread_number.setValue(config.thread_number)
        advanced_layout.addRow(_('THREAD_NUMBER'), self.input_thread_number)
        self.input_cloze_str = QLineEdit(getattr(config, 'cloze_str', '{{c1::%s}}'))
        self.input_sound_str = QLineEdit(config.sound_str)
        advanced_layout.addRow(_('CLOZE_WORD_FORMAT'), self.input_cloze_str)
        advanced_layout.addRow(_('SOUND_FORMAT'), self.input_sound_str)
        add_page(advanced, tr('词典设置'))
        tabs.tabBar().moveTab(2, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self.reset)
        outer.addWidget(buttons)
        self.watch_changes(self.widget_values)

    def _toggle_css(self, checked):
        self.css_panel.setVisible(checked)
        self.css_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        if checked:
            self.resize(max(self.width(), 660), max(self.height(), 650))

    def read_configuration(self):
        from ..query.background import active_job
        if active_job():
            QMessageBox.information(self, tr('读取配置'), tr('请等待当前查询任务结束后再读取配置。'))
            return
        filename, _ = QFileDialog.getOpenFileName(self, tr('读取配置'), config.media_dir,
                                                  tr('FastCard Maker 配置 (*.json)'))
        if not filename:
            return
        try:
            if Path(filename).suffix.lower() != '.json':
                raise ValueError()
            from ..utils.config_storage import read_object
            settings = read_object(filename)
            if isinstance(settings, dict) and settings.get('format') in ('fastcm-local', 'fastcm-backup'):
                settings = settings.get('settings')
            from ..utils.config_storage import validate_settings
            validate_settings(settings, importing=True)
            answer = QMessageBox.question(self, tr('读取配置'),
                tr('读取文件中的设置到本机？本机词典路径和 API Key 保留，媒体配置暂不覆盖。'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                return
            config.import_settings(settings)
        except (OSError, ValueError, TypeError):
            QMessageBox.warning(self, tr('配置读取失败'), tr('无法读取配置文件，请检查文件格式或权限。原配置未重置。'))
            return
        from ..service.ai_config import clear_session_keys
        clear_session_keys()
        self.configuration_loaded = True
        QMessageBox.information(self, tr('读取配置'),
            tr('已读取到本机。下次打开选项时，可选择是否覆盖媒体配置。'))
        self.reject()

    def reset(self):
        from .backup_controls import choose_mode
        choose_mode(self, 'auto')
        self.backup_api_keys.setChecked(True)
        self.language_combo.setCurrentIndex(0)
        self.ai_send_mode.setCurrentIndex(0)
        self.ai_rate.setValue(29)
        self.ai_timeout.setValue(90)
        self.ai_connect_timeout.setValue(10)
        self.ai_retries.setValue(2)
        self.ai_markdown.setChecked(True)
        self.ai_css_enabled.setChecked(False)
        self.style_css.setPlainText(DEFAULT_CSS)
        self.auto_enabled.setChecked(False)
        self.auto_interval.setValue(5)
        for i in range(self.style_types.count()):
            self.style_types.item(i).setCheckState(Qt.CheckState.Checked)
        for i in range(self.auto_models.count()):
            self.auto_models.item(i).setCheckState(Qt.CheckState.Unchecked)
        for box in (self.check_force_update, self.check_ignore_accents, self.check_ighore_mdx_wordcase):
            box.setChecked(False)
        self.check_fuzzy_match.setChecked(True)
        self.input_thread_number.setValue(16)
        self.input_cloze_str.setText('{{c1::%s}}')
        self.input_sound_str.setText('[sound:{0}]')

    def pending_settings(self):
        selected = [self.auto_models.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.auto_models.count()) if self.auto_models.item(i).checkState() == Qt.CheckState.Checked]
        return {
            'backup_mode': self._backup_mode,
            'backup_api_keys': self.backup_api_keys.isChecked(),
            'ui_language': self.language_combo.currentData(),
            'ai_send_mode': self.ai_send_mode.currentData(),
            'ai_markdown': self.ai_markdown.isChecked(),
            'ai_css_enabled': self.ai_css_enabled.isChecked(),
            'ai_css': self.style_css.toPlainText(),
            'ai_styles': {str(self.style_types.item(i).data(Qt.ItemDataRole.UserRole)): {'enabled': self.style_types.item(i).checkState() == Qt.CheckState.Checked} for i in range(self.style_types.count())},
            'auto_run': {'enabled': self.auto_enabled.isChecked(), 'interval_minutes': self.auto_interval.value(), 'model_ids': selected},
            'force_update': self.check_force_update.isChecked(),
            'ignore_accents': self.check_ignore_accents.isChecked(),
            'ignore_mdx_wordcase': self.check_ighore_mdx_wordcase.isChecked(),
            'fuzzy_match': self.check_fuzzy_match.isChecked(),
            'thread_number': self.input_thread_number.value(),
            'cloze_str': self.input_cloze_str.text(), 'sound_str': self.input_sound_str.text()}

    def save(self):
        if self.ai_css_enabled.isChecked():
            try:
                rules(self.style_css.toPlainText())
            except ValueError as error:
                QMessageBox.warning(self, tr('AI 内容格式'), str(error))
                return False
        try:
            config.update({'backup_mode': self._backup_mode})
            save_transport(self.ai_rate.value(), self.ai_timeout.value(), self.ai_connect_timeout.value(), self.ai_retries.value(),
                           backup_api_keys=self.backup_api_keys.isChecked())
        except ValueError as error:
            QMessageBox.warning(self, tr('AI 设置'), str(error))
            return False
        from ..service.ai_support.store import read_settings
        credentials = read_settings().get('keys', {})
        config.update(dict(self.pending_settings(), credential_backup=credentials if self.backup_api_keys.isChecked() else {}))

    def accept(self):
        previous = getattr(config, 'ui_language', '')
        if self.save() is False:
            return
        if previous != self.language_combo.currentData():
            from ..service.refresh import get_updater
            get_updater().request()
        super().accept()
