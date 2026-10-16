# -*- coding:utf-8 -*-
"""Small settings tabs; global AI styling is applied by successful query writes."""
from copy import deepcopy
from aqt import mw
from aqt.qt import *
from ..context import config
from ..lang import _
from ..translations import text as tr
from ..i18n import languages
from ..utils.ai_format import DEFAULT_CSS, global_css, rules
from .base import Dialog
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
        form.addRow(tr('AI 发送方式'), self.ai_send_mode)
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
            form.addRow(label, control)
        self.ai_markdown = QCheckBox(tr('解析 Markdown（标题、表格、列表等）'))
        self.ai_markdown.setChecked(bool(getattr(config, 'ai_markdown', True)))
        general_layout.addWidget(self.ai_markdown)
        self.ai_css_enabled = QCheckBox(tr('启用 CSS 注入（默认关闭）'))
        self.ai_css_enabled.setChecked(bool(getattr(config, 'ai_css_enabled', False)))
        general_layout.addWidget(self.ai_css_enabled)
        tip = QLabel(tr('只在笔记实际写入成功后，为勾选的类型注入样式。保存设置不会修改卡片 CSS。'))
        tip.setWordWrap(True)
        general_layout.addWidget(tip)
        self.css_toggle = QToolButton()
        self.css_toggle.setText(tr('查看／编辑全局 CSS'))
        self.css_toggle.setCheckable(True)
        self.css_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.css_toggle.setArrowType(Qt.ArrowType.RightArrow)
        general_layout.addWidget(self.css_toggle)
        panel = self.css_panel = QWidget()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        general_layout.addWidget(QLabel(tr('生效的笔记类型（默认全选，开启 CSS 注入后生效）')))
        self.style_types = QListWidget()
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
        tip = QLabel(tr('所有类型共用一份样式，重点美化表格。只更新标记的 AI 样式区块，保留其他卡片 CSS。'))
        tip.setWordWrap(True)
        panel_layout.addWidget(tip)
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
        language_form.addRow(tr('界面语言'), self.language_combo)
        auto_layout.addLayout(language_form)
        language_tip = QLabel(tr('保存后重新打开窗口以应用语言。'))
        language_tip.setWordWrap(True)
        auto_layout.addWidget(language_tip)
        settings = getattr(config, 'auto_run', {})
        settings = settings if isinstance(settings, dict) else {}
        self.auto_enabled = QCheckBox(tr('启用定时制作'))
        self.auto_enabled.setChecked(bool(settings.get('enabled', False)))
        auto_layout.addWidget(self.auto_enabled)
        interval = QHBoxLayout()
        interval.addWidget(QLabel(tr('检测间隔（分钟）')))
        self.auto_interval = QSpinBox()
        self.auto_interval.setRange(1, 1440)
        self.auto_interval.setValue(settings.get('interval_minutes', 5))
        interval.addWidget(self.auto_interval)
        auto_layout.addLayout(interval)
        self.auto_models = QListWidget()
        selected = {str(v) for v in settings.get('model_ids', [])}
        for model in mw.col.models.all():
            item = QListWidgetItem(model['name'], self.auto_models)
            item.setData(Qt.ItemDataRole.UserRole, model['id'])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if str(model['id']) in selected else Qt.CheckState.Unchecked)
        auto_layout.addWidget(QLabel(tr('勾选参与自动制作的笔记类型')))
        auto_layout.addWidget(self.auto_models)
        tip = QLabel(tr('使用点亮星星的配置。只处理启用后新增笔记的空字段；上一批未结束时跳过本轮。Anki 关闭后停止。'))
        tip.setWordWrap(True)
        auto_layout.addWidget(tip)
        add_page(automatic, tr('通用设置'))

        advanced = QWidget()
        advanced_layout = QFormLayout(advanced)
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
        language_form.addRow(_('CLOZE_WORD_FORMAT'), self.input_cloze_str)
        advanced_layout.addRow(_('SOUND_FORMAT'), self.input_sound_str)
        add_page(advanced, tr('词典设置'))
        tabs.tabBar().moveTab(2, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Reset)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Reset).clicked.connect(self.reset)
        outer.addWidget(buttons)

    def _toggle_css(self, checked):
        self.css_panel.setVisible(checked)
        self.css_toggle.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
        if checked:
            self.resize(max(self.width(), 660), max(self.height(), 650))

    def reset(self):
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

    def save(self):
        selected = [self.auto_models.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.auto_models.count()) if self.auto_models.item(i).checkState() == Qt.CheckState.Checked]
        if self.auto_enabled.isChecked():
            for mid in selected:
                conf = config.get_maps(mid)
                index = conf.get('auto', -1) if isinstance(conf, dict) else -1
                if type(index) is not int or not isinstance(conf, dict) or not 0 <= index < len(conf.get('list', [])):
                    QMessageBox.warning(self, tr('自动运行配置'), tr('请先为参与自动运行的笔记类型点亮一个配置星星。'))
                    return False
        if self.ai_css_enabled.isChecked():
            try:
                rules(self.style_css.toPlainText())
            except ValueError as error:
                QMessageBox.warning(self, tr('AI 内容格式'), str(error))
                return False
        try:
            save_transport(self.ai_rate.value(), self.ai_timeout.value(), self.ai_connect_timeout.value(), self.ai_retries.value())
        except ValueError as error:
            QMessageBox.warning(self, tr('AI 设置'), str(error))
            return False
        config.update({
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
            'cloze_str': self.input_cloze_str.text(), 'sound_str': self.input_sound_str.text()})

    def accept(self):
        previous = getattr(config, 'ui_language', '')
        if self.save() is False:
            return
        if previous != self.language_combo.currentData():
            from ..service.refresh import get_updater
            get_updater().request()
        super().accept()
