from ..translations import text as tr
import os
from aqt.qt import *

from ..context import config
from .base import Dialog
from ..utils.logger import logger
from ..service.custom_scripts import process_and_copy_custom_py
from .folder_layout import build_folder_layout

__all__ = ['FoldersManageDialog']

class FoldersManageDialog(Dialog):
    '''
    Dictionary folder manager window with 3-way Safe Exit, Dirty Flag, and deferred transaction execution.
    '''

    def __init__(self, parent, title=None):
        title = title or tr('词典目录管理器 (Folder Manager)')
        super(FoldersManageDialog, self).__init__(parent, title)

        self.resize(650, 550)
        # 将当前配置缓存到内存中，未点击保存前不直接落地
        self._current_folders = list(config.dirs)
        self._is_dirty = False  # 【新增】：初始化脏标记

        self.plugin_dict_folder = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), 'service', 'dict'
        )
        self.build()

    def reject(self):
        """
        重写关闭事件：只有在内容被修改过（_is_dirty == True）时才弹窗拦截
        """
        if not getattr(self, '_is_dirty', False):
            super(FoldersManageDialog, self).reject()  # 没修改过，静默退出
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
            self.accept()  # 执行保存并退出
        elif clicked_button == discard_btn:
            super(FoldersManageDialog, self).reject()  # 直接放弃修改并退出
        else:
            pass  # 取消，留在当前界面继续编辑

    def build(self):
        build_folder_layout(self)

    def refresh_tree(self):
        """刷新树形菜单（纯预览，不在此处写盘修改）"""
        self.tree.clear()

        for folder in self._current_folders:
            if not os.path.isdir(folder):
                err_node = QTreeWidgetItem(self.tree)
                err_node.setText(0, tr('📁 %s [路径已失效或被删除]') % folder)
                err_node.setForeground(0, QBrush(QColor("#D32F2F")))
                err_node.setData(0, Qt.ItemDataRole.UserRole, folder)
                continue

            folder_node = QTreeWidgetItem(self.tree)
            folder_node.setText(0, f"📁 {folder}")
            folder_node.setData(0, Qt.ItemDataRole.UserRole, folder)

            f = folder_node.font(0)
            f.setBold(True)
            folder_node.setFont(0, f)
            folder_node.setExpanded(True)

            try:
                for root_dir, dirs, files in os.walk(folder):
                    for file in files:
                        if file.lower().endswith('.mdx'):
                            mdx_path = os.path.join(root_dir, file)
                            py_name = file[:-4] + '.py'
                            py_path = os.path.join(root_dir, py_name)
                            display_name = os.path.relpath(mdx_path, folder)

                            mdx_node = QTreeWidgetItem(folder_node)
                            mdx_node.setText(0, f"📄 {display_name}")
                            mdx_node.setData(0, Qt.ItemDataRole.UserRole, mdx_path)

                            if os.path.exists(py_path):
                                mdx_node.setText(1, tr('✅ 就绪 (待保存)'))
                                mdx_node.setForeground(1, QBrush(QColor("#2E7D32")))
                            else:
                                mdx_node.setText(1, tr('➖ 无 Python 脚本'))
                                mdx_node.setForeground(1, QBrush(QColor("#9E9E9E")))
            except Exception as e:
                logger.error(f"扫描目录树发生异常: {str(e)}")
                continue

    def add_folder(self):
        dir_ = QFileDialog.getExistingDirectory(
            self,
            caption=tr('选择包含词典的文件夹'),
            directory=config.last_folder,
            options=QFileDialog.Option.ShowDirsOnly | QFileDialog.Option.DontResolveSymlinks)
        if dir_:
            if dir_ not in self._current_folders:
                self._current_folders.append(dir_)
                self._is_dirty = True  # 【新增】：标记为已修改
                logger.info(f"内存暂存：添加本地词典文件夹: [{dir_}]")
                self.refresh_tree()
            config.update({'last_folder': dir_})

    def remove_folder(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.warning(self, tr("未选中目录"), tr("请先在下方列表中点击选中需要移除的根文件夹。"))
            return

        if item.parent():
            item = item.parent()

        folder_path = item.data(0, Qt.ItemDataRole.UserRole)
        if folder_path in self._current_folders:
            self._current_folders.remove(folder_path)
            self._is_dirty = True  # 【新增】：标记为已修改
            logger.info(f"内存暂存：移除本地词典文件夹: [{folder_path}]")
            self.refresh_tree()

    def open_selected_path(self):
        item = self.tree.currentItem()
        if not item:
            QMessageBox.warning(self, tr("提示"), tr("请先在下方列表中选中一个目录或文件。"))
            return

        path = item.data(0, Qt.ItemDataRole.UserRole)
        if path:
            if os.path.isfile(path):
                path = os.path.dirname(path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))

    @property
    def dirs(self):
        return self._current_folders

    def accept(self):
        """Save immediately; the caller schedules script synchronization in the background."""
        self.save()
        super(FoldersManageDialog, self).accept()

    def force_hot_reload(self):
        import sys
        import importlib

        logger.info("目录管理器退出，触发词典脚本热重载...")
        plugin_name = __name__.split('.')[0]
        dict_prefix = f"{plugin_name}.service.dict"

        for k in list(sys.modules.keys()):
            if k.startswith(dict_prefix):
                del sys.modules[k]

        from ..service import service_pool
        service_pool.clean()

    def save(self):
        data = {
            'dirs': self.dirs,
            'use_filename': self.chk_use_filename.isChecked(),
            'export_media': self.chk_export_media.isChecked()
        }
        config.update(data)
