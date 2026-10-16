"""Unified local/network dictionary controls and folder settings."""
from aqt.qt import *
from ..translations import text as tr
from ..context import config
from ..service import service_manager
from .foldermanager import FoldersManageDialog
from .flow_layout import FlowLayout


def build_dict_layout(self):
    controls = QHBoxLayout()
    self.enabled_all_check_btn = QCheckBox(tr('全选 / 取消全选'))
    self.enabled_all_check_btn.clicked.connect(self.enabled_all_changed)
    controls.addWidget(self.enabled_all_check_btn)
    controls.addStretch()
    self.detect_button = QPushButton(tr('检测目录'))
    self.detect_button.setToolTip(tr('检测当前目录中的词典；勾选并保存后启用。'))
    self.detect_button.clicked.connect(self.detect_directories)
    controls.addWidget(self.detect_button)
    self.main_layout.addLayout(controls)
    self.scan_label = QLabel()
    self.scan_label.setWordWrap(True)
    self.scan_label.hide()
    self.main_layout.addWidget(self.scan_label)
    self.management_tabs = QTabWidget()
    self.dictionary_pages = []
    for title in (tr('本地词典'), tr('网络词典')):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content.setStyleSheet('background-color: palette(base); color: palette(text);')
        grid = QGridLayout(content)
        grid.setColumnStretch(0, 1)
        grid.setVerticalSpacing(10)
        scroll.setWidget(content)
        self.management_tabs.addTab(scroll, title)
        self.dictionary_pages.append((content, grid))
    self.folders = FoldersManageDialog(self)
    self.folders.setWindowFlags(Qt.WindowType.Widget)
    self.folders.setModal(False)
    for buttons in self.folders.findChildren(QDialogButtonBox):
        buttons.hide()
    self.management_tabs.addTab(self.folders, tr('词典目录'))
    self.main_layout.addWidget(self.management_tabs)
    self.populate_dictionaries(service_manager)
    action_widget = QWidget()
    bottom = FlowLayout(action_widget)
    self.open_scripts_dir_btn = QPushButton(tr('📂 打开脚本所在目录'))
    self.open_scripts_dir_btn.clicked.connect(self.open_global_scripts_dir)
    bottom.addWidget(self.open_scripts_dir_btn)
    import_btn = QPushButton(tr('导入脚本'))
    import_btn.clicked.connect(self.import_script)
    bottom.addWidget(import_btn)
    trash_btn = QPushButton('🗑️')
    trash_btn.setToolTip(tr('查看回收站中的旧脚本'))
    trash_btn.clicked.connect(self.open_trash)
    bottom.addWidget(trash_btn)
    restore_btn = QPushButton(tr('恢复旧脚本'))
    restore_btn.clicked.connect(self.restore_old_script)
    bottom.addWidget(restore_btn)
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    buttons.accepted.connect(self.accept)
    buttons.rejected.connect(self.reject)
    self.main_layout.addWidget(action_widget)
    save_row = QHBoxLayout()
    save_row.addStretch()
    save_row.addWidget(buttons)
    self.main_layout.addLayout(save_row)
