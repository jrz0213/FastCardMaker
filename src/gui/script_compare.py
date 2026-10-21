"""Two-column mutually exclusive file choices and a read-only source viewer."""
from aqt.qt import *
from .base import Dialog
from ..translations import text as tr
from .help_widgets import with_help
from ..service import script_backup as storage


class ScriptCompareDialog(Dialog):
    def __init__(self, parent, local, backup):
        super().__init__(parent, tr('选择保留的脚本'))
        self.local, self.backup = local, backup
        self.initial = storage.digest(local), storage.digest(backup)
        self.resize(800, 480)
        layout = QVBoxLayout(self)
        layout.addWidget(with_help(QLabel(tr('选择保留的脚本')), tr('版本选择说明'), tr(
            '本机版本是当前运行副本；备份版本是媒体库 ZIP 中的当前脚本，不是回收站里的旧版本。'
            '默认选备份，每行只能保留一侧，表头勾选可全选一侧。\n\n'
            '打开只读查看，不运行代码。选择“不存在”的一侧表示删除该文件，确认前会再次提示。'
            '未确认或取消时不会应用选择。确认前会再次检测文件是否变化，防止覆盖期间的新修改。')))
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr('文件'), tr('本机版本'), tr('备份版本')])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().hide()
        self.table.verticalHeader().hide()
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        layout.addWidget(self.table)
        header = QWidget()
        heads = QGridLayout(header)
        heads.setContentsMargins(0, 0, 0, 0)
        heads.setSpacing(0)
        heads.addWidget(QLabel(tr('文件')), 0, 0)
        self.heads = [QCheckBox(tr('本机版本')), QCheckBox(tr('备份版本'))]
        self.rows = []
        for side, check in enumerate(self.heads):
            check.setTristate(True)
            check.clicked.connect(lambda checked, s=side: self.select_all(s))
            heads.addWidget(check, 0, side + 1)
        for column in range(3):
            heads.setColumnStretch(column, 1)
        header.setStyleSheet('QLabel, QCheckBox { font-weight: bold; padding: 8px; background: palette(button); }')
        layout.insertWidget(1, header)
        for name in sorted(set(local) | set(backup)):
            if local.get(name) == backup.get(name):
                continue
            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(name))
            group = QButtonGroup(self)
            group.setExclusive(True)
            checks = []
            for side, files in enumerate((local, backup)):
                cell = QWidget()
                box = QHBoxLayout(cell)
                check = QCheckBox(('%.2f KB' % (len(files[name]['source'].encode('utf-8')) / 1024))
                                  if name in files else tr('不存在'))
                group.addButton(check)
                checks.append(check)
                check.setChecked(side == 1)
                check.toggled.connect(self.refresh_headers)
                button = QPushButton(tr('打开'))
                button.setStyleSheet('QPushButton:disabled { color: palette(mid); }')
                button.setEnabled(name in files)
                button.clicked.connect(lambda checked=False, n=name, f=files: self.view(n, f))
                box.addWidget(check)
                box.addWidget(button)
                self.table.setCellWidget(row, side + 1, cell)
            self.rows.append((name, checks, group))
        self.table.resizeRowsToContents()
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.refresh_headers()

    def select_all(self, side):
        for _, checks, _ in self.rows:
            checks[side].setChecked(True)
        self.refresh_headers()

    def refresh_headers(self, *_):
        for side, check in enumerate(self.heads):
            count = sum(checks[side].isChecked() for _, checks, _ in self.rows)
            check.blockSignals(True)
            check.setCheckState(Qt.CheckState.Checked if count == len(self.rows) else
                                Qt.CheckState.PartiallyChecked if count else Qt.CheckState.Unchecked)
            check.blockSignals(False)

    def view(self, name, files):
        dialog = Dialog(self, name)
        dialog.resize(850, 600)
        layout = QVBoxLayout(dialog)
        editor = QPlainTextEdit(files[name]['source'])
        editor.setReadOnly(True)
        layout.addWidget(editor)
        dialog.exec()

    def accept(self):
        merged = dict(self.local)
        for name, checks, _ in self.rows:
            selected = self.local if checks[0].isChecked() else self.backup
            if name in selected:
                merged[name] = selected[name]
            else:
                merged.pop(name, None)
        removed = set(self.local) - set(merged)
        if removed and QMessageBox.question(self, tr('确认删除'), '\n'.join(sorted(removed)),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        try:
            storage.apply_selection(merged, *self.initial)
        except (OSError, ValueError) as error:
            QMessageBox.warning(self, tr('脚本同步失败'), str(error))
            return
        super().accept()


def check_scripts(parent):
    from ..utils.backup_store import automatic
    if not automatic():
        return True
    try:
        local, remote = storage.observe()
        if remote is None or local == remote:
            storage.auto_publish()
            return True
        dialog = ScriptCompareDialog(parent, local, remote)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted:
            from ..service.refresh import get_updater
            get_updater().request()
        return accepted
    except (OSError, ValueError, SyntaxError) as error:
        QMessageBox.warning(parent, tr('脚本同步失败'), str(error))
        return False
