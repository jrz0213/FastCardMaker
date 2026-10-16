"""Explicit local/media settings direction before opening Options."""
from aqt.qt import QMessageBox
from ..context import config
from ..translations import text as tr


def check_settings(parent):
    try:
        differences = config.settings_difference()
        if not differences:
            return True
        labels = {'ai_settings': tr('AI 设置'), 'dicts': tr('词典启用状态'),
                  'auto_run': tr('自动运行配置')}
        names = [tr('笔记类型配置：') + key if key.isdigit() else labels.get(key, key)
                 for key in differences]
        dialog = QMessageBox(parent)
        dialog.setWindowTitle(tr('配置不同'))
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setText(tr('本机配置与媒体文件夹配置不同，请选择处理方式。'))
        dialog.setInformativeText(tr('覆盖：本机 → 媒体文件夹；同步：媒体文件夹 → 本机；取消：保持不变。词典路径仅存本机；API Key 是否同步取决于备份开关。'))
        dialog.setDetailedText('\n'.join(names))
        overwrite = dialog.addButton(tr('覆盖'), QMessageBox.ButtonRole.ActionRole)
        sync = dialog.addButton(tr('同步'), QMessageBox.ButtonRole.ActionRole)
        dialog.addButton(QMessageBox.StandardButton.Cancel)
        dialog.setDefaultButton(QMessageBox.StandardButton.Cancel)
        dialog.exec()
        action = 'overwrite' if dialog.clickedButton() is overwrite else 'sync' if dialog.clickedButton() is sync else 'cancel'
        config.resolve_settings(action)
        if action == 'sync':
            from ..service.ai_config import clear_session_keys
            clear_session_keys()
            from ..service.refresh import get_updater
            get_updater().request()
        return True
    except (OSError, ValueError):
        config.resolve_settings('cancel')
        QMessageBox.warning(parent, tr('配置读取失败'), tr('无法读取配置文件，请检查文件格式或权限。原配置未重置。'))
        return True
