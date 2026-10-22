"""Build the AI settings form, collapsible details, and action buttons."""

from aqt.qt import *
from ...translations import text as tr
from ...service.ai_config import PRESETS
from ...service.ai_keys import key_store_path
from ..model_input import ModelInput
from ..flow_layout import FlowLayout
from ..help_widgets import with_help
from ..masked_key import MaskedKeyEdit


def build_settings_layout(self):
    layout = QVBoxLayout(self)
    body = QHBoxLayout()
    self.list = QListWidget()
    self.list.setMinimumWidth(220)
    self.list.setMaximumWidth(300)
    body.addWidget(self.list)
    panel = QWidget()
    panel_layout = QVBoxLayout(panel)
    basic_form = QFormLayout()
    basic_form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    basic_form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    panel_layout.addLayout(basic_form)
    self.loading = False
    self.provider = QComboBox()
    for key, (name, _, _) in PRESETS.items():
        self.provider.addItem(name, key)
    self.name = QLineEdit()
    self.address = QLineEdit()
    self.address.setPlaceholderText('https://example.com/v1/responses')
    self.address.setToolTip(tr('API 地址（含接口路径）'))
    self.address.editingFinished.connect(self.address_edited)
    self.key = MaskedKeyEdit()
    self.key.setPlaceholderText(tr('点击确定后保存在本机，重启后仍保留'))
    self.key.setToolTip(tr('完整 API Key 仅保存在系统凭证库：Windows 凭据管理器、macOS 钥匙串。不进入配置或 ZIP 备份。平时显示前 3 位和后 3 位，编辑时隐藏。'))
    self.model = ModelInput()
    self.mode = QComboBox()
    self.mode.addItem('Responses API', 'responses')
    self.mode.addItem('Chat Completions API', 'chat')
    self.mode.addItem('Gemini Interactions API', 'interactions')
    self.mode.addItem('Claude Messages API', 'messages')
    # Retain the internal value for old profile handling; the URL selects it.
    self.mode.setParent(self)
    self.mode.hide()
    self.send_mode = QComboBox()
    self.send_mode.addItem(tr('逐字段发送（默认）'), 'field')
    self.send_mode.addItem(tr('按笔记合并发送'), 'note')
    self.send_mode.setToolTip(tr('合并同一笔记使用此 AI 配置的字段，一次回复后分别填入。'))
    for label, widget in [(tr('服务预设'), self.provider), (tr('配置名称'), self.name),
                          (tr('API 地址'), self.address),
                          ('API Key', self.key), (tr('调用模型'), self.model)]:
        if widget is self.address:
            widget = with_help(widget, tr('AI 连接说明'), tr(
                '填写完整 API 地址，包含域名后的接口路径，插件按地址识别协议。模型名称必须是该服务实际提供的模型 ID。'
                '预设只是起点，可按自己的服务修改地址和模型。\n\n'
                'API Key 点击确定后保存到本机系统凭证库，换设备后重新填写。'
                '切换字段的 AI 连接不会修改该字段的提示词。'))
        basic_form.addRow(label, widget)
    self.send_hint = QLabel()
    self.send_hint.setWordWrap(True)
    self.send_hint.setParent(self)
    self.send_hint.hide()
    self.send_mode.setParent(self)
    self.send_mode.hide()
    def update_send_hint():
        self.send_hint.setText(tr('合并发送：每个字段仍填写自己的提示词；程序自动拆分回复，支持 Markdown 表格。')
                               if self.send_mode.currentData() == 'note' else
                               tr('逐字段发送：每个目标字段单独请求，保持原有逻辑。'))
    self.send_mode.currentIndexChanged.connect(update_send_hint)
    update_send_hint()
    self.warning = QLabel()
    self.warning.setWordWrap(True)
    self.warning.hide()
    panel_layout.addWidget(self.warning)
    self.skill = QPlainTextEdit(self)
    panel_layout.addWidget(with_help(QLabel(tr('Skill（当前 AI 配置）')), tr('Skill 说明'), tr(
        'Skill 是当前 AI 连接在普通字段查询时使用的补充指令，词典 AI 解析不使用它。'
        '{{字段名}} 请写在字段映射的提示词中。AI 发送方式在插件设置中全局设置。')))
    self.skill.setPlaceholderText(tr('例如：你是英语老师。用中文解释，回复简洁，使用基础 Markdown。'))
    self.skill.setMinimumHeight(100)
    self.skill.setMaximumHeight(140)
    self.skill.setInputMethodHints(Qt.InputMethodHint.ImhNone)
    self.skill.setToolTip(tr('普通 AI 字段查询使用此指令；词典 AI 解析不使用 Skill。{{字段名}} 请填在字段映射的提示词中。'))
    panel_layout.addWidget(self.skill)
    self.details = QToolButton()
    self.details.setText(tr('更多配置（Details）'))
    self.details.setCheckable(True)
    self.details.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
    self.details.setArrowType(Qt.ArrowType.RightArrow)
    panel_layout.addWidget(self.details)
    self.advanced = QWidget()
    form = QFormLayout(self.advanced)
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
    self.form = form
    self.parameters = QPlainTextEdit()
    self.parameters.setMinimumHeight(180)
    self.parameters.setPlaceholderText('{"temperature": 1, "top_p": 1}')
    form.addRow(tr('自由参数（JSON）'), self.parameters)
    self.hint = QLabel()
    self.hint.setWordWrap(True)
    self.hint.setParent(self)
    self.hint.hide()
    parameters_help = tr(
        '可填写完整 JSON 对象或键值片段，例如 "temperature": 1, "top_p": 1。'
        '不同服务／模型支持的参数不同，请参考下方服务备注，不支持的参数需删除。'
        '模型、消息正文和认证信息由插件填写，不能在这里覆盖。\n\n')
    form.addRow(with_help(QLabel(tr('参数说明')), tr('自由参数说明'), lambda: parameters_help + self.hint.text()))
    panel_layout.addWidget(self.advanced)
    self.advanced.hide()
    self.details.toggled.connect(self.toggle_details)
    panel_layout.addStretch()
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    scroll.setWidget(panel)
    body.addWidget(scroll, 1)
    layout.addLayout(body)
    actions = QWidget()
    buttons = FlowLayout(actions)
    add = QPushButton(tr('新增配置'))
    remove = QPushButton(tr('删除配置'))
    add.clicked.connect(self.add_profile)
    remove.clicked.connect(self.remove_profile)
    buttons.addWidget(add)
    buttons.addWidget(remove)
    self.reset_keys = QPushButton(tr('重试读取凭证'))
    self.reset_keys.setVisible(self._keys_locked)
    self.reset_keys.clicked.connect(self.retry_credentials)
    buttons.addWidget(self.reset_keys)
    open_folder = QPushButton(tr('打开配置目录'))
    open_folder.clicked.connect(self.open_settings_folder)
    buttons.addWidget(open_folder)
    box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    box.accepted.connect(self.accept)
    box.rejected.connect(self.reject)
    layout.addWidget(actions)
    save = QHBoxLayout()
    save.addStretch()
    save.addWidget(box)
    layout.addLayout(save)
    self.list.currentRowChanged.connect(self.select_profile)
    self.provider.currentIndexChanged.connect(self.apply_preset)
    self.name.textChanged.connect(self.update_name)
    self.mode.currentIndexChanged.connect(self.refresh_options)
    self.model.editTextChanged.connect(self.refresh_options)
    for section in (basic_form, form):
        for row in range(section.rowCount()):
            item = section.itemAt(row, QFormLayout.ItemRole.LabelRole)
            if item and isinstance(item.widget(), QLabel):
                item.widget().setWordWrap(True)
