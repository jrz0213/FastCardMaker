from ..translations import text as tr
"""Construct the dictionary management dialog layout."""

from aqt.qt import *

from ..context import config
from ..lang import _
from .flow_layout import FlowLayout

def build_folder_layout(self):
    self.main_layout = QVBoxLayout(self)
    self.main_layout.setContentsMargins(16, 16, 16, 16)
    self.main_layout.setSpacing(12)

    toolbar = QWidget()
    toolbar_layout = FlowLayout(toolbar)

    self.add_btn = QPushButton(tr("➕ 添加本地词典文件夹..."))
    self.add_btn.setToolTip(tr("选择一个包含 MDX/MDD 词典文件的根目录"))
    self.add_btn.setMinimumHeight(32)
    self.add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.add_btn.setStyleSheet("""
            QPushButton {
                padding: 0 15px;
                border-radius: 4px;
                background-color: palette(button);
                border: 1px solid palette(mid);
                color: palette(button-text);
                font-weight: bold;
            }
            QPushButton:hover { background-color: palette(mid); }
        """)

    self.remove_btn = QPushButton(tr("➖ 移除选中项"))
    self.remove_btn.setToolTip(tr("从管理列表中暂时移除选中的文件夹"))
    self.remove_btn.setMinimumHeight(32)
    self.remove_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.remove_btn.setStyleSheet("""
            QPushButton {
                padding: 0 15px;
                border-radius: 4px;
                background-color: palette(button);
                border: 1px solid palette(mid);
                color: palette(button-text);
            }
            QPushButton:hover { background-color: palette(mid); }
        """)

    self.open_btn = QPushButton(tr("📂 打开所在位置"))
    self.open_btn.setToolTip(tr("在系统中打开选中的文件夹或词典所在目录"))
    self.open_btn.setMinimumHeight(32)
    self.open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    self.open_btn.setStyleSheet("""
            QPushButton {
                padding: 0 15px;
                border-radius: 4px;
                background-color: palette(button);
                border: 1px solid palette(mid);
                color: palette(button-text);
                font-weight: bold;
            }
            QPushButton:hover { background-color: palette(mid); }
        """)

    self.add_btn.clicked.connect(self.add_folder)
    self.remove_btn.clicked.connect(self.remove_folder)
    self.open_btn.clicked.connect(self.open_selected_path)  # 打开位置操作是只读的，不触发脏标记

    toolbar_layout.addWidget(self.add_btn)
    toolbar_layout.addWidget(self.remove_btn)
    toolbar_layout.addWidget(self.open_btn)

    self.tree = QTreeWidget()
    self.tree.setColumnCount(2)
    self.tree.setHeaderLabels([tr('词典资源目录与文件'), tr('脚本解析状态')])
    self.tree.setColumnWidth(0, 420)
    self.tree.setColumnWidth(1, 120)
    self.tree.setAlternatingRowColors(True)
    self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    self.tree.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    self.tree.setStyleSheet("""
            QTreeWidget {
                border: 1px solid palette(mid);
                border-radius: 6px;
                outline: 0;
            }
            QTreeWidget::item { padding: 4px 0; }
            QHeaderView::section {
                padding: 6px;
                border: none;
                border-bottom: 1px solid palette(mid);
                background-color: palette(button);
                color: palette(button-text);
                font-weight: bold;
            }
        """)

    options_group = QGroupBox(tr("额外查询配置"))
    options_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid palette(mid);
                border-radius: 6px;
                margin-top: 10px;
                padding-top: 15px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                subcontrol-position: top left;
                padding: 0 5px;
                left: 10px;
            }
        """)
    options_layout = QHBoxLayout(options_group)
    options_layout.setContentsMargins(15, 10, 15, 15)

    self.chk_use_filename = QCheckBox(_('CHECK_FILENAME_LABEL'))
    self.chk_export_media = QCheckBox(_('EXPORT_MEDIA'))
    self.chk_use_filename.setChecked(config.use_filename)
    self.chk_export_media.setChecked(config.export_media)
    self.chk_use_filename.setCursor(Qt.CursorShape.PointingHandCursor)
    self.chk_export_media.setCursor(Qt.CursorShape.PointingHandCursor)

    # 【新增】：勾选配置发生变化时，标记为已修改
    self.chk_use_filename.stateChanged.connect(lambda: setattr(self, '_is_dirty', True))
    self.chk_export_media.stateChanged.connect(lambda: setattr(self, '_is_dirty', True))

    options_layout.addWidget(self.chk_use_filename)
    options_layout.addWidget(self.chk_export_media)
    options_layout.addStretch()

    btnbox = QDialogButtonBox(
        QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        Qt.Orientation.Horizontal,
        self
    )
    btnbox.accepted.connect(self.accept)
    btnbox.rejected.connect(self.reject)

    self.main_layout.addWidget(toolbar)
    self.main_layout.addWidget(self.tree)
    self.main_layout.addWidget(options_group)
    self.main_layout.addWidget(btnbox)

    self.refresh_tree()
