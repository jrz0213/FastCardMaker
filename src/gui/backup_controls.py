"""Unified backup mode and explicit portable ZIP import/export."""
from datetime import datetime
from pathlib import Path
from aqt.qt import *
from ..context import config
from ..translations import text as tr
from .help_widgets import with_help


def build_controls(dialog, layout):
    group = QGroupBox(tr('配置保存'))
    box = QVBoxLayout(group)
    dialog.backup_mode = QToolButton()
    dialog.backup_mode.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
    menu = QMenu(dialog.backup_mode)
    actions = QActionGroup(menu)
    actions.setExclusive(True)
    dialog.backup_modes = {}
    mode = getattr(config, 'data', {}).get('backup_mode', 'auto')
    for code, label in (('auto', tr('自动备份')), ('manual', tr('手动备份'))):
        action = menu.addAction(label)
        action.setCheckable(True)
        actions.addAction(action)
        action.setChecked(mode == code)
        dialog.backup_modes[code] = action
        action.triggered.connect(lambda checked, value=code: choose_mode(dialog, value))
    dialog.backup_mode.setMenu(menu)
    box.addWidget(with_help(dialog.backup_mode, tr('配置保存'), tr(
        '自动备份：保存修改后，将 AI 配置和当前 Python 脚本更新到媒体库 ZIP，随 Anki 媒体同步。'
        '手动备份：AI 配置和脚本只保存到本机，使用导入／导出 ZIP 自行传递。普通设置、字段配置和脚本勾选状态始终保存在媒体配置中。\n\n'
        '词典路径、MDX／MDD 文件、词典附带 JS、对话记录和回收站中的旧脚本不进入备份。'
        '旧脚本仅在本机保留七天，恢复为当前脚本后才参与备份。\n\n'
        'API Key 只保存在本机系统凭证库，不参与同步和备份；换设备后重新填写。'
        '导入缺少密钥的备份不会清空已有密钥。导出只包含已保存的配置，当前页面的修改需要先点击确定保存。')))
    box.addWidget(QLabel(tr('API Key 仅存本机系统凭证库，不参与同步和备份。')))
    dialog.backup_manual = QWidget()
    buttons = QHBoxLayout(dialog.backup_manual)
    buttons.setContentsMargins(0, 0, 0, 0)
    dialog.import_backup_button = QPushButton(tr('导入 ZIP'))
    dialog.export_backup_button = QPushButton(tr('导出 ZIP'))
    dialog.export_backup_button.setToolTip(tr('导出已保存的配置；当前页面未保存的修改不会包含在内。'))
    dialog.import_backup_button.clicked.connect(lambda: import_backup(dialog))
    dialog.export_backup_button.clicked.connect(lambda: export_backup(dialog))
    buttons.addWidget(dialog.import_backup_button)
    buttons.addWidget(dialog.export_backup_button)
    box.addWidget(dialog.backup_manual)
    layout.addWidget(group)
    choose_mode(dialog, mode)


def choose_mode(dialog, mode):
    mode = mode if mode in ('auto', 'manual') else 'auto'
    dialog._backup_mode = mode
    dialog.backup_modes[mode].setChecked(True)
    dialog.backup_mode.setText(tr('手动备份' if mode == 'manual' else '自动备份'))
    dialog.backup_manual.setVisible(mode == 'manual')


def export_backup(dialog):
    from ..service.script_library import snapshot, script_directory
    from ..service.ai_support.store import read_settings
    from ..utils.backup_store import write_bundle
    from ..utils.config_storage import portable
    name = '_fastcm_' + datetime.now().strftime('%Y%m%d_%H%M%S') + '.zip'
    path, _ = QFileDialog.getSaveFileName(dialog, tr('导出 ZIP'), str(Path(config.media_dir) / name), '*.zip')
    if not path:
        return
    try:
        if Path(path).suffix.lower() != '.zip':
            path += '.zip'
        ai = read_settings()
        data = {'ai_settings': portable(ai)}
        write_bundle(path, settings=portable(data), scripts=snapshot(script_directory()))
        QMessageBox.information(dialog, tr('导出 ZIP'), tr('备份已导出。'))
    except (OSError, ValueError, SyntaxError) as error:
        QMessageBox.warning(dialog, tr('导出 ZIP'), str(error))


def import_backup(dialog):
    from ..utils.backup_store import read_bundle
    from ..service.script_library import install_library
    from ..service.ai_config import clear_session_keys
    path, _ = QFileDialog.getOpenFileName(dialog, tr('导入 ZIP'), config.media_dir, '*.zip')
    if not path:
        return
    try:
        if Path(path).suffix.lower() != '.zip':
            raise ValueError('Expected a ZIP backup')
        bundle = read_bundle(path)
        if bundle is None:
            raise ValueError('Backup not found')
        if QMessageBox.question(dialog, tr('导入 ZIP'), tr('用备份中的配置和脚本更新本机？当前页面未保存的修改将放弃，导入后关闭此页。缺失的 API Key 不会清空本机密钥。'),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No) != QMessageBox.StandardButton.Yes:
            return
        from ..service.ai_support.migration import scrub, _profiles
        cleaned = scrub(bundle['settings'], _profiles(getattr(config, 'data', {})))
        if cleaned != bundle['settings']:
            from ..utils.backup_store import write_bundle
            write_bundle(path, settings=cleaned)
            bundle['settings'] = cleaned
        # Import does not switch the device's selected backup mode.
        incoming = dict(bundle['settings'], backup_mode=dialog._backup_mode)
        from ..utils.config_storage import validate_settings
        validate_settings(incoming, importing=True)
        install_library(bundle['scripts'])
        config.import_settings(incoming)
        clear_session_keys()
        dialog.configuration_loaded = True
        from ..service.refresh import get_updater
        get_updater().request()
        dialog.done(QDialog.DialogCode.Rejected)
    except (OSError, ValueError, SyntaxError) as error:
        QMessageBox.warning(dialog, tr('导入 ZIP'), str(error))
