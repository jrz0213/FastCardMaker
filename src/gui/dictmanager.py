from ..translations import text as tr
import os
import sys
import importlib
from copy import deepcopy
from types import SimpleNamespace
from aqt.qt import *

from ..context import config
from ..service import service_manager, service_pool
from .base import Dialog
from ..utils.logger import logger
from ..service.dictionary_groups import grouped_sources
from ..service.script_updates import history_directory, trash_directory, restore_script, recycle_script

from .dict_layout import build_dict_layout

__all__ = ['DictManageDialog']


class DictManageDialog(Dialog):
    """
    Dictionary manager window with Safe Exit interception, 3-way choice, and Dirty Flag.
    (Simplified UI: Removed custom editor, kept individual edit btn, global dir btn at bottom left)
    """

    def __init__(self, parent, title=None):
        title = title or tr('词典管理')
        super(DictManageDialog, self).__init__(parent, title)

        logger.info("打开词典管理面板 (DictManageDialog)...")

        # 移除了顶部设置框后，高度缩减更紧凑
        self.resize(740, 570)

        # 主容器与间距
        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(16, 16, 16, 16)
        self.main_layout.setSpacing(15)

        self._options = list()
        self._is_dirty = False  # 初始化脏标记
        self._closed = False
        self.preview_loader = None
        self._choices = deepcopy(config.dicts)

        # 全局统一的脚本目录路径
        self.plugin_dict_folder = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'service', 'dict'
        )

        self.build()

    def reject(self):
        """
        重写关闭事件：只有内容被修改过（_is_dirty == True）时才弹窗拦截
        """
        if not (getattr(self, '_is_dirty', False) or self.folders._is_dirty):
            super(DictManageDialog, self).reject()  # 没修改过，静默退出
            return

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(tr('确认退出'))
        msg_box.setText(tr('检测到有未保存的更改，是否保存？'))

        save_btn = msg_box.addButton(tr('保存并退出'), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg_box.addButton(tr('不保存退出'), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg_box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()

        clicked_button = msg_box.clickedButton()
        if clicked_button == save_btn:
            self.accept()  # 触发保存并退出
        elif clicked_button == discard_btn:
            super(DictManageDialog, self).reject()  # 放弃修改直接退出
        else:
            pass  # 取消，留在当前界面继续编辑

    def build(self):
        build_dict_layout(self)

    def populate_dictionaries(self, registry):
        for row in self._options:
            for unique in row.get('uniques', [row['unique']]):
                self._choices.setdefault(unique, {})['enabled'] = row['check_btn'].isChecked()
        self._options = []
        for _, grid in self.dictionary_pages:
            while grid.count():
                widget = grid.takeAt(0).widget()
                if widget:
                    widget.deleteLater()
        local = grouped_sources(registry, self._choices)
        network = [{'primary': item, 'uniques': [item.__unique__], 'script_paths': [getattr(item, '__path__', '')],
                    'title': item.__title__, 'dict_path': ''} for item in registry.web_services]
        for page, services in enumerate((local, network)):
            self.dicts_layout = self.dictionary_pages[page][1]
            seen = set()
            for group in services:
                factory = group['primary']
                if factory.__unique__ in seen:
                    continue
                seen.add(factory.__unique__)
                kind = tr('自定义脚本') if group['script_paths'] else tr('默认解析')
                title = group['title'] + (' · ' + kind if page == 0 else '')
                script = next(iter(group['script_paths']), '')
                self.add_dict_layout(len(seen) - 1, title=title, unique=factory.__unique__, path=script,
                    mdx_path=group['dict_path'], script_paths=group['script_paths'], uniques=group['uniques'],
                    enabled=any(self._choices.get(unique, {}).get('enabled', False) for unique in group['uniques']))
            self.dicts_layout.setRowStretch(len(seen), 1)
        self.enabled_all_update()

    def detect_directories(self):
        if self.preview_loader is not None:
            return
        from .service_loader import ServiceLoaderThread
        from ..service.refresh import scan_registry
        choices = deepcopy(self._choices)
        for row in self._options:
            for unique in row.get('uniques', [row['unique']]):
                choices.setdefault(unique, {})['enabled'] = row['check_btn'].isChecked()
        settings = SimpleNamespace(dirs=list(self.folders.dirs), dicts=choices, folder_sync=False)
        class Preview:
            def load_services(self, cancelled=None, progress=None):
                return {'registry': scan_registry(settings, cancelled)}
        loader = self.preview_loader = ServiceLoaderThread(Preview())
        self.detect_button.setEnabled(False)
        self.scan_label.setText(tr('正在后台检测词典目录…'))
        self.scan_label.show()
        loader.finished_signal.connect(self._detected)
        loader.failed.connect(self._detection_failed)
        loader.finished.connect(self._detection_finished)
        loader.start()

    def _detected(self, result):
        if not self._closed:
            self.populate_dictionaries(result['registry'])
            self.scan_label.setText(tr('检测完成，新词典默认未勾选；保存后应用。'))

    def _detection_failed(self, *_):
        if not self._closed:
            self.scan_label.setText(tr('目录检测失败，原选择保留。'))

    def _detection_finished(self):
        if not self._closed:
            self.preview_loader = None
            self.detect_button.setEnabled(True)

    def generate_script(self, dict_path, script_paths=None, class_name=None):
        from .script_generator import ScriptGeneratorDialog
        dialog = ScriptGeneratorDialog(self, dict_path, script_paths, class_name)
        dialog.saved.connect(lambda *_: self.detect_directories())
        dialog.exec()
        dialog.deleteLater()

    def done(self, result):
        self._closed = True
        if self.preview_loader:
            self.preview_loader.stop()
            self.preview_loader = None
        super().done(result)

    def add_dict_layout(self, i, **kwargs):
        title, unique, enabled, path = (
            kwargs.get('title', u''),
            kwargs.get('unique', u''),
            kwargs.get('enabled', False),
            kwargs.get('path', u'')
        )

        # 勾选框
        check_btn = QCheckBox(f" {title}")
        # 自适应 Expanding 宽度，避免文字截断和溢出
        check_btn.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        check_btn.setEnabled(True)
        check_btn.setChecked(enabled)
        check_btn.setCursor(Qt.CursorShape.PointingHandCursor)

        # 独立的编辑脚本按钮
        btn_style = """
            QPushButton {
                padding: 4px 10px;
                border-radius: 4px;
                background-color: palette(button);
                border: 1px solid palette(mid);
                color: palette(button-text);
            }
            QPushButton:hover { background-color: palette(midlight); }
            QPushButton:disabled { color: palette(mid); }
        """

        edit_btn = QPushButton(tr("📝 编辑脚本"))
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setStyleSheet(btn_style)

        if path and os.path.isfile(path):
            edit_btn.setToolTip(f"使用系统默认程序打开: {path}")
        else:
            edit_btn.setEnabled(False)

        # 绑定信号
        # 1. 只有启停状态改变时，才标记页面为脏
        check_btn.stateChanged.connect(lambda: setattr(self, '_is_dirty', True))
        check_btn.stateChanged.connect(self.enabled_all_update)

        # 2. 点击编辑，不影响脏标记
        edit_btn.clicked.connect(lambda checked=False, p=path: self.on_edit(p))
        edit_btn.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        edit_btn.customContextMenuRequested.connect(lambda point, p=path, button=edit_btn: self.script_menu(button, point, p))

        # 添加到网格，只有 2 列
        label_box = QWidget()
        label_layout = QVBoxLayout(label_box)
        label_layout.setContentsMargins(0, 0, 0, 0)
        label_layout.setSpacing(2)
        label_layout.addWidget(check_btn)
        dict_path = kwargs.get('mdx_path', '')
        missing_label = QLabel(tr('未找到本地词典文件'))
        font = missing_label.font()
        font.setPointSize(max(8, font.pointSize() - 2))
        missing_label.setFont(font)
        missing_label.setStyleSheet('color: palette(mid);')
        missing_label.setVisible(not bool(dict_path and os.path.isfile(dict_path)))
        label_layout.addWidget(missing_label)
        self.dicts_layout.addWidget(label_box, i, 0)
        self.dicts_layout.addWidget(edit_btn, i, 1)
        generate_btn = QPushButton(tr('AI 解析'))
        generate_btn.setStyleSheet(btn_style)
        generate_btn.setEnabled(bool(dict_path.lower().endswith('.mdx') and os.path.isfile(dict_path)))
        generate_btn.clicked.connect(lambda checked=False, p=dict_path, paths=kwargs.get('script_paths', []),
                                    cls=unique: self.generate_script(p, paths, cls if paths else None))
        self.dicts_layout.addWidget(generate_btn, i, 2)

        self._options.append({
            'unique': unique,
            'uniques': kwargs.get('uniques', [unique]),
            'missing_label': missing_label,
            'check_btn': check_btn,
            'edit_btn': edit_btn,
            'generate_btn': generate_btn
        })

    def enabled_all_update(self):
        b = True
        for row in self._options:
            if not row['check_btn'].isChecked():
                b = False
                break
        # 防止初始化时的信号互相干扰，暂时解除脏标记关联
        self.enabled_all_check_btn.blockSignals(True)
        self.enabled_all_check_btn.setChecked(b)
        self.enabled_all_check_btn.blockSignals(False)

    def enabled_all_changed(self):
        self._is_dirty = True
        b = self.enabled_all_check_btn.isChecked()
        for row in self._options:
            row['check_btn'].setChecked(b)

    def on_edit(self, path):
        """调起系统默认程序打开单体脚本文件"""
        logger.info(f"调用系统默认程序打开文件: [{path}]")
        try:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
        except Exception as e:
            logger.error(f"编辑词典脚本文件失败: {str(e)}")

    def script_menu(self, button, point, path):
        if not path or not os.path.isfile(path):
            return
        menu = QMenu(button)
        remove = menu.addAction(tr('删除脚本（移入回收站）'))
        if menu.exec(button.mapToGlobal(point)) == remove:
            try:
                recycle_script(path, self.plugin_dict_folder)
                self.scan_label.setText(tr('脚本已移入回收站，可恢复。'))
                self.scan_label.show()
                self.detect_directories()
            except (OSError, ValueError):
                self.scan_label.setText(tr('无法删除脚本。'))
                self.scan_label.show()

    def open_global_scripts_dir(self):
        """打开全局的解析脚本所在目录"""
        if not os.path.exists(self.plugin_dict_folder):
            try:
                os.makedirs(self.plugin_dict_folder, exist_ok=True)
            except Exception as e:
                logger.error(f"创建脚本目录失败: {e}")

        QDesktopServices.openUrl(QUrl.fromLocalFile(self.plugin_dict_folder))
        logger.info(f"使用系统资源管理器打开脚本目录: [{self.plugin_dict_folder}]")

    def open_history(self):
        self._open_archive(False)

    def open_trash(self):
        self._open_archive(True)

    def _open_archive(self, recycled):
        try:
            folder = trash_directory(self.plugin_dict_folder) if recycled else history_directory(self.plugin_dict_folder)
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError()
        except (OSError, ValueError):
            self.scan_label.setText(tr('无法打开对话记录目录或回收站。'))
            self.scan_label.show()

    def restore_old_script(self):
        filename, _ = QFileDialog.getOpenFileName(self, tr('恢复旧脚本'), str(trash_directory(self.plugin_dict_folder)), '*.py.bak')
        if not filename:
            return
        try:
            restore_script(filename, self.plugin_dict_folder)
            self.scan_label.setText(tr('旧脚本已恢复，重新检测后应用。'))
            self.detect_directories()
        except (OSError, ValueError, SyntaxError):
            self.scan_label.setText(tr('恢复旧脚本失败。'))
        self.scan_label.show()

    def accept(self):
        """点击确认或选择保存并退出时触发"""
        self.save()
        super(DictManageDialog, self).accept()

    def force_hot_reload(self):
        """强制清理 Python 内存缓存，实现词典脚本热更新"""
        logger.info("词典启停面板退出，触发配置与脚本热重载...")
        plugin_name = __name__.split('.')[0]
        dict_prefix = f"{plugin_name}.service.dict"

        for k in list(sys.modules.keys()):
            if k.startswith(dict_prefix):
                del sys.modules[k]

        from ..service import service_pool
        service_pool.clean()

    def save(self):
        """save config to file"""
        data = dict()
        dicts = deepcopy(config.dicts)
        dicts.update(deepcopy(self._choices))
        for row in self._options:
            for unique in row.get('uniques', [row['unique']]):
                dicts.setdefault(unique, {})['enabled'] = row['check_btn'].isChecked()
        data['dicts'] = dicts
        data.update(dirs=self.folders.dirs, use_filename=self.folders.chk_use_filename.isChecked(),
                    export_media=self.folders.chk_export_media.isChecked())
        config.update(data)
        logger.info(f"保存词典启用状态配置成功 | 共 {len(dicts)} 个词典配置")
