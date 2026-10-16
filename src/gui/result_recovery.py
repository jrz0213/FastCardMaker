"""Startup and manual recovery of durable results in a modeless dialog."""

from aqt import mw
from aqt.qt import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, Qt, QTimer
from ..translations import text as tr
from ..utils.media import profile_token


def show_recovery(parent=None):
    from aqt.utils import tooltip
    from ..query.result_cache import ResultCache
    from ..query.background import active_job
    if active_job():
        active_job().show_progress()
        tooltip(tr('已有更新任务正在运行，请完成或取消后再开始。'))
        return
    cache = ResultCache()
    try:
        records = cache.read()
    except Exception:
        tooltip(tr('无法读取待写入缓存，请保留缓存文件以便排查。'))
        return
    if not records:
        tooltip(tr('没有待恢复的结果。'))
        return
    token = profile_token()
    existing = getattr(mw, '_fwq_recovery_dialog', None)
    if existing is not None:
        if getattr(existing, '_fwq_profile_token', None) == token:
            existing.show()
            existing.raise_()
            existing.activateWindow()
            return existing
        existing.close()
    dialog = QDialog(parent or mw)
    dialog._fwq_profile_token = token
    mw._fwq_recovery_dialog = dialog
    def released():
        if getattr(mw, '_fwq_recovery_dialog', None) is dialog:
            mw._fwq_recovery_dialog = None
    dialog.destroyed.connect(released)
    dialog.setWindowTitle('FastCM - ' + tr('恢复未写入结果'))
    dialog.setWindowModality(Qt.WindowModality.NonModal)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    layout = QVBoxLayout(dialog)
    label = QLabel(tr('有 %s 条已返回但未写入的结果。恢复不会再次调用 AI；修改过的字段会跳过，缺失的媒体会报错。') % len(records))
    label.setWordWrap(True)
    layout.addWidget(label)
    buttons = QHBoxLayout()
    restore, discard, later = [QPushButton(tr(text)) for text in ('恢复结果', '丢弃这些缓存', '稍后')]
    for button in (restore, discard, later):
        buttons.addWidget(button)
    layout.addLayout(buttons)
    def recover():
        if token != profile_token():
            dialog.close()
            return
        from ..query.background import recover_results
        try:
            recover_results(parent or mw)
            dialog.close()
        except Exception:
            label.setText(tr('恢复失败，缓存仍保留，请查看日志。'))
    def remove():
        if active_job():
            label.setText(tr('已有更新任务正在运行，请完成或取消后再开始。'))
            return
        if token == profile_token():
            try:
                cache.remove([key for key, _ in records])
            except Exception:
                label.setText(tr('缓存清理失败，请查看日志。'))
                return
        dialog.close()
    restore.clicked.connect(recover)
    discard.clicked.connect(remove)
    later.clicked.connect(dialog.close)
    dialog.resize(540, 150)
    dialog.show()
    dialog.raise_()
    return dialog


def notify_recovery():
    from aqt.utils import tooltip
    from ..query.result_cache import ResultCache
    token = profile_token()
    def notify():
        if token != profile_token():
            return
        try:
            if ResultCache().pending():
                show_recovery(mw)
        except Exception:
            tooltip(tr('无法读取待写入缓存，请保留缓存文件以便排查。'))
    QTimer.singleShot(500, notify)
