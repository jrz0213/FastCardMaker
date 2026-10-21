"""Choose a recycled Python source to inspect or restore, without executing it."""
from datetime import datetime
import re
import tokenize
from pathlib import Path
from aqt.qt import *
from .base import Dialog
from .help_widgets import with_help
from ..translations import text as tr
from ..service.script_updates import trash_directory, prune_old_scripts


class ScriptRecycleDialog(Dialog):
    def __init__(self, parent, directory):
        super().__init__(parent, tr('恢复旧脚本'))
        self.directory, self.selected_path = directory, None
        self.resize(680, 400)
        layout = QVBoxLayout(self)
        layout.addWidget(with_help(QLabel(tr('旧版本（仅本机）')), tr('旧版本说明'), tr(
            '这里只列出本机被删除或替换的旧脚本，不进入自动备份或手动导出 ZIP，也不会同步到其他设备。'
            '文件名后显示进入回收站的时间，超过七天会清理。\n\n'
            '打开：只读查看源码，不执行。恢复：替换对应的当前脚本，替换前会保留当前版本。'
            '恢复完成后，该文件作为当前脚本按备份设置处理。右上角 × 关闭列表，不恢复任何文件。')))
        self.files = QListWidget()
        layout.addWidget(self.files)
        prune_old_scripts(directory)
        for path in sorted(trash_directory(directory).glob('script_*.py.bak'), reverse=True):
            match = re.fullmatch(r'script_(\d{8}_\d{6}_\d{6})_(.+\.py)\.bak', path.name)
            if not match or path.is_symlink():
                continue
            try:
                stamp = datetime.strptime(match[1], '%Y%m%d_%H%M%S_%f').strftime('%Y-%m-%d %H:%M:%S')
            except ValueError:
                continue
            item = QListWidgetItem(match[2] + ' · ' + stamp)
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            self.files.addItem(item)
        buttons = QHBoxLayout()
        self.restore_button = QPushButton(tr('恢复'))
        self.open_button = QPushButton(tr('打开'))
        self.restore_button.clicked.connect(self.accept)
        self.open_button.clicked.connect(self.open_source)
        buttons.addWidget(self.restore_button)
        buttons.addWidget(self.open_button)
        layout.addLayout(buttons)
        self.files.currentRowChanged.connect(self.refresh)
        if self.files.count():
            self.files.setCurrentRow(0)
        else:
            layout.insertWidget(1, QLabel(tr('暂无可恢复的旧脚本。')))
        self.refresh()

    def refresh(self, *_):
        enabled = self.files.currentItem() is not None
        self.restore_button.setEnabled(enabled)
        self.open_button.setEnabled(enabled)

    def open_source(self):
        item = self.files.currentItem()
        if item is None:
            return
        path = Path(item.data(Qt.ItemDataRole.UserRole))
        try:
            with tokenize.open(path) as stream:
                source = stream.read(500001)
            if len(source) > 500000:
                raise ValueError('Script is too large')
            viewer = Dialog(self, path.name)
            viewer.resize(780, 540)
            layout = QVBoxLayout(viewer)
            text = QPlainTextEdit(source)
            text.setReadOnly(True)
            layout.addWidget(text)
            viewer.exec()
        except (OSError, ValueError, SyntaxError, UnicodeError) as error:
            QMessageBox.warning(self, tr('打开'), str(error))

    def accept(self):
        item = self.files.currentItem()
        if item:
            self.selected_path = item.data(Qt.ItemDataRole.UserRole)
            super().accept()
