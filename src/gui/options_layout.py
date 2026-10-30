"""Build the configuration window toolbar, tab container, and footer."""

from ..translations import text as tr

from aqt import mw
from aqt.qt import *

from ..constants import Endpoint
from ..context import config
from ..utils import get_icon
from .options_widgets import CTabBar
from .flow_layout import FlowLayout

def build_options_layout(self, s):
    """主界面组件构建"""
    if s != 'after_build': return

    # 1. 顶部：卡片类型选择与全局按钮
    top_layout = QHBoxLayout()
    top_layout.setContentsMargins(0, 0, 0, 5)

    model_label = QLabel(tr("笔记类型:"))
    model_font = QFont()
    model_font.setBold(True)
    model_label.setFont(model_font)

    self.model_combo = QComboBox()
    self.model_combo.setMinimumWidth(220)
    self.model_combo.setCursor(Qt.CursorShape.PointingHandCursor)
    self.model_combo.setStyleSheet("""
            QComboBox {
                padding: 4px 10px;
                border: 1px solid rgba(128, 128, 128, 0.4);
                border-radius: 4px;
                font-weight: bold;
            }
        """)

    models = mw.col.models.all_names_and_ids()
    sorted_models = sorted(models, key=lambda item: item.name)

    self.model_combo.blockSignals(True)
    for i, m in enumerate(sorted_models):
        self.model_combo.addItem(m.name, userData=m.id)
        if self.current_model and m.id == self.current_model['id']:
            self.model_combo.setCurrentIndex(i)
    # Saved mappings may refer to deleted or other-profile note types.
    # Keep those mappings in storage, but only offer live types here.
    self.model_combo.blockSignals(False)
    from .configuration_style import style_note_types
    style_note_types(self.model_combo)
    self.model_combo.currentIndexChanged.connect(self.on_model_combo_changed)

    top_layout.addWidget(model_label)
    top_layout.addWidget(self.model_combo)
    top_layout.addWidget(QLabel(tr('字段配置')))
    self.configuration_combo = QComboBox()
    self.configuration_combo.setMinimumWidth(160)
    self.configuration_combo.currentIndexChanged.connect(self.select_configuration)
    top_layout.addWidget(self.configuration_combo, 1)
    self.configuration_star = QToolButton()
    self.configuration_star.setCheckable(True)
    self.configuration_star.setToolTip(tr('设为当前笔记类型的默认配置'))
    self.configuration_star.clicked.connect(self.set_default_configuration)
    top_layout.addWidget(self.configuration_star)
    more = QToolButton()
    more.setText('⋯')
    more.setToolTip(tr('配置操作'))
    more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(more)
    menu.addAction(tr('新增配置'), lambda: self.addTab())
    self.rename_configuration_button = menu.addAction(tr('重命名配置'), self.rename_configuration)
    self.copy_configuration_action = menu.addAction(tr('复制配置'), self.copy_configuration)
    self.delete_configuration_button = menu.addAction(tr('删除配置'), lambda: self.removeTab(self.tab_widget.currentIndex()))
    menu.addSeparator()
    self.auto_configuration_action = menu.addAction(tr('用于自动运行'))
    self.auto_configuration_action.setCheckable(True)
    self.auto_configuration_action.triggered.connect(self.use_selected_for_automatic)
    more.setMenu(menu)
    top_layout.addWidget(more)
    top_layout.addStretch()

    top_btn_style = """
            QPushButton {
                padding: 5px 12px;
                border-radius: 4px;
                background-color: transparent;
                border: 1px solid rgba(128, 128, 128, 0.3);
            }
            QPushButton:hover { background-color: rgba(128, 128, 128, 0.15); }
        """

    dm_btn = QPushButton(tr('词典管理'))
    dm_btn.setToolTip(tr('统一管理目录、本地词典、网络词典和解析脚本'))
    dm_btn.clicked.connect(self.show_dm_dialog)

    paras_btn = QPushButton(tr('插件设置'))
    paras_btn.setToolTip(tr("通用参数设置"))
    paras_btn.clicked.connect(self.show_paras)

    ai_btn = QPushButton(tr('AI 设置'))
    ai_btn.clicked.connect(self.show_ai_settings)
    refresh_btn = QPushButton(tr('重新检测词典'))
    refresh_btn.setToolTip(tr('重新扫描词典和脚本，并重试初始化失败的本地词典；不会更新卡片字段。'))
    refresh_btn.clicked.connect(self.refresh_sources)

    self.main_layout.addLayout(top_layout)
    actions = QWidget()
    action_layout = FlowLayout(actions)
    for btn in [ai_btn, dm_btn, refresh_btn]:
        btn.setStyleSheet(top_btn_style)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        action_layout.addWidget(btn)
    self.main_layout.addWidget(actions)

    # 2. 中部：核心配置标签页 (Main Viewport)
    self.tab_widget = QTabWidget()
    self.tab_widget.setObjectName('fwqConfigurationTabs')
    self.tab_widget.setDocumentMode(True)
    self.tab_widget.setStyleSheet('''
        QTabWidget#fwqConfigurationTabs::tab-bar { alignment: left; }
        QTabWidget#fwqConfigurationTabs::pane { border: 1px solid palette(mid); }
    ''')
    self.tab_widget.setTabBar(CTabBar(parent_dialog=self))
    self.tab_widget.tabBar().hide()

    tab_corner = QWidget()
    tab_corner_layout = QHBoxLayout(tab_corner)
    tab_corner_layout.setContentsMargins(0, 0, 2, 0)

    tab_add_button = QToolButton(self)
    tab_add_button.setText('+')
    tab_add_button.setAutoRaise(True)
    tab_add_button.setFixedSize(30, 30)
    tab_add_button.setToolTip(tr("新增一份字段映射配置"))
    tab_add_button.clicked.connect(self.addTab)
    tab_corner_layout.addWidget(tab_add_button)

    tab_corner.hide()
    self.tab_widget.tabCloseRequested.connect(self.removeTab)
    self.main_layout.addWidget(self.tab_widget, 1)

    # 3. 底部：日志、批量扫描、关于与保存区 (Footer)
    footer_actions = QWidget()
    bottom_layout = FlowLayout(footer_actions)
    bottom_layout.setContentsMargins(0, 5, 0, 0)

    self.log_toggle_btn = QPushButton()
    self.update_log_btn_text()
    self.log_toggle_btn.clicked.connect(self.toggle_logging)

    self.open_log_btn = QPushButton(tr('打开日志'))
    self.open_log_btn.clicked.connect(self.open_log_file)

    about_btn = QPushButton(tr('关于'))
    about_btn.clicked.connect(self.show_about)

    for btn in [self.log_toggle_btn, self.open_log_btn, paras_btn, about_btn]:
        btn.setStyleSheet(top_btn_style)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        bottom_layout.addWidget(btn)

    home_label = QLabel(f'<a href="{Endpoint.user_guide}" style="text-decoration:none; color:#2196F3; font-weight:bold; margin-left: 10px;">{tr("使用手册")}</a>')
    home_label.setOpenExternalLinks(True)

    btnbox = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, Qt.Orientation.Horizontal, self)
    btnbox.accepted.connect(self.accept)
    btnbox.rejected.connect(self.reject)

    bottom_layout.addWidget(home_label)
    self.main_layout.addWidget(footer_actions)
    save_layout = QHBoxLayout()
    save_layout.addStretch()
    save_layout.addWidget(btnbox)
    self.main_layout.addLayout(save_layout)

    if self.current_model:
        self.build_tabs_layout()
    else:
        self.sync_configuration_selector()
