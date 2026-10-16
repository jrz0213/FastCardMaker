"""Configuration dialog lifecycle and user actions."""

from ..translations import text as tr

from aqt import mw
from copy import deepcopy
from aqt.qt import *

from ..lang import _
from ..context import config
from .base import WIDGET_SIZE, Dialog
from .setting import SettingDialog
from .options_controller import OptionsController
from .service_loader import ServiceLoaderThread
from ..service.refresh import get_updater
from ..utils.media import profile_token
from .options_layout import build_options_layout
from .options_tab import TabContent
from .options_widgets import NoScrollComboBox, CTabBar

__all__ = ['OptionsDialog']


class OptionsDialog(Dialog):
    '''
    核心配置台窗口 (View)
    负责界面的渲染、用户的点击响应，并将复杂逻辑交由 OptionsController 处理
    '''

    __slot__ = ['after_build']
    _signal = pyqtSignal(str)

    # =========================================================================
    # 第一部分：初始化与生命周期 (Init & Lifecycle)
    # =========================================================================
    def __init__(self, parent, title=None, model_id=-1):
        title = title or tr('FastCard Maker 核心配置台')
        super(OptionsDialog, self).__init__(parent, title)
        self.setModal(False)
        self.setWindowModality(Qt.WindowModality.NonModal)

        # 挂载后台逻辑控制器 (Controller)
        self.controller = OptionsController()
        self._is_dirty = False
        self._closed = False
        self._loading = False
        self._load_error = False
        self._profile_token = profile_token()
        self.loader_thread = None
        self.default_tab_index = 0
        self.auto_tab_index = -1

        self.main_layout = QVBoxLayout(self)
        self.main_layout.setContentsMargins(12, 12, 12, 12)
        self.main_layout.setSpacing(10)

        self.model_id = model_id if model_id != -1 else self.controller.get_last_model_id()
        self.current_model = None
        self.tabs = []

        if self.model_id:
            self.current_model = mw.col.models.get(self.model_id)

        if not self.current_model and mw.col.models.all():
            self.current_model = mw.col.models.all()[0]
            self.model_id = self.current_model['id']

        target_width = WIDGET_SIZE.dialog_width + 150
        target_height = 550
        if self.current_model:
            target_height = min(max(4, len(self.current_model['flds']) + 1), 14) * 45 + 180
        self.resize(target_width, target_height)

        # 启动时的等待动画
        self.loading_label = QLabel(tr('正在加载内容来源，请稍候...'))
        self.loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(self.loading_label)

        self.dict_services = self.controller.preview_services()
        self._after_build('after_build')
        self._updater = get_updater()
        from .task_progress import progress_hub
        self._progress_hub = progress_hub()
        self._progress_hub.started.connect(self._attach_progress)
        self._task_strip = None
        recent = self._progress_hub.current or self._progress_hub.last
        if recent and recent.token == self._profile_token:
            self._attach_progress(recent)
        self._updater.updated.connect(self._registry_updated)
        self._updater.started.connect(self._registry_started)
        self._updater.failed.connect(self._load_failed)
        self._updater.idle.connect(self._registry_idle)
        if self.controller.needs_background_load():
            self._start_loading()
        elif not self._updater.busy:
            self.loading_label.hide()
        if self._updater.busy:
            self._registry_started()
        if hasattr(mw, 'dict_signals'):
            mw.dict_signals.status_changed.connect(self.check_dict_status)

    def _start_loading(self):
        if self._closed:
            return
        self._stop_loading()
        self._loading = True
        self._load_error = False
        self.loading_label.setText(tr('正在后台加载内容来源…'))
        self.loading_label.show()
        loader = self.loader_thread = ServiceLoaderThread(self.controller)
        loader.finished_signal.connect(self._on_services_loaded)
        loader.failed.connect(self._load_failed)
        loader.progress.connect(self._load_progress)
        loader.finished.connect(self._loader_finished)
        loader.start()

    def _stop_loading(self):
        loader, self.loader_thread = self.loader_thread, None
        if loader is not None:
            loader.stop()
            for signal, slot in ((loader.finished_signal, self._on_services_loaded),
                                 (loader.failed, self._load_failed), (loader.progress, self._load_progress),
                                 (loader.finished, self._loader_finished)):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self._loading = False

    def _loader_finished(self):
        if self.sender() is self.loader_thread:
            self.loader_thread = None

    def _load_progress(self, done, total):
        if not self._closed and self.sender() is self.loader_thread:
            self.loading_label.setText(tr('正在后台加载内容来源：%s / %s') % (done, total))

    def _load_failed(self, *_):
        sender = self.sender()
        if not self._closed and (sender is None or sender is self.loader_thread or sender is self._updater):
            self._loading = False
            self._load_error = True
            self.loading_label.setText(tr('词典检测失败，请点击“重新检测词典”重试。'))
            self.loading_label.show()

    def _registry_started(self):
        if not self._closed:
            self._stop_loading()
            self._load_error = False
            self.loading_label.setText(tr('正在后台更新词典和脚本，完成后自动刷新…'))
            self.loading_label.show()

    def _registry_updated(self):
        if not self._closed and self._profile_token == profile_token():
            self._start_loading()

    def _registry_idle(self):
        if not self._closed and not self._loading and not self._load_error:
            self.loading_label.hide()

    def refresh_sources(self):
        self.retry_dictionaries()
        self._updater.request()

    def _attach_progress(self, job):
        if self._closed:
            return
        from .task_progress import TaskProgress
        if self._task_strip:
            self._task_strip.deleteLater()
        self._task_strip = TaskProgress(job, self)
        self.main_layout.insertWidget(0, self._task_strip)

    def done(self, result):
        if self._closed:
            return
        self._closed = True
        self._stop_loading()
        self._progress_hub.started.disconnect(self._attach_progress)
        for signal, slot in ((self._updater.updated, self._registry_updated),
                             (self._updater.started, self._registry_started),
                             (self._updater.failed, self._load_failed),
                             (self._updater.idle, self._registry_idle)):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
        super().done(result)

    def reject(self):
        """窗口关闭拦截：脏标记检测与安全退出"""
        changed = (self.mapping_values() != self._initial_mapping_values if hasattr(self, '_initial_mapping_values')
                   else getattr(self, '_is_dirty', False))
        if not changed:
            self.done(QDialog.DialogCode.Rejected)
            return

        msg_box = QMessageBox(self)
        msg_box.setIcon(QMessageBox.Icon.Warning)
        msg_box.setWindowTitle(tr('确认退出'))
        msg_box.setText(tr('检测到您修改了字段映射或配置，是否保存更改？'))

        save_btn = msg_box.addButton(tr('保存并退出'), QMessageBox.ButtonRole.AcceptRole)
        discard_btn = msg_box.addButton(tr('不保存退出'), QMessageBox.ButtonRole.DestructiveRole)
        cancel_btn = msg_box.addButton(tr('取消'), QMessageBox.ButtonRole.RejectRole)

        msg_box.exec()

        clicked_button = msg_box.clickedButton()
        if clicked_button == save_btn:
            self.accept()
        elif clicked_button == discard_btn:
            self.done(QDialog.DialogCode.Rejected)


    # =========================================================================
    # 第二部分：页面渲染构建 (UI Rendering)
    # =========================================================================
    def _on_services_loaded(self, dict_services):
        """后台服务加载完毕后的 UI 刷新回调"""
        if self._closed or self._profile_token != profile_token():
            return
        if self.sender() is not None and self.sender() is not self.loader_thread:
            return
        self._loading = False
        self.dict_services = dict_services
        self.controller.dict_services = dict_services
        for tab in self.tabs:
            tab.refresh_dict_combos(dict_services)
        if self._updater.busy:
            self._registry_started()
        else:
            self.loading_label.hide()

    def _after_build(self, s):
        build_options_layout(self, s)

    def build_tabs_layout(self):
        """构建标签页内的字段映射矩阵"""
        try:
            self.tab_widget.currentChanged.disconnect()
        except Exception:
            pass
        while len(self.tabs) > 0:
            self.removeTab(0, True)

        conf = self.controller.get_maps(self.current_model['id'])
        maps_list = {'list': [conf], 'def': 0} if isinstance(conf, list) else conf
        self.default_tab_index = maps_list.get('def', 0)
        selected = maps_list.get('auto', -1)
        self.auto_tab_index = selected if type(selected) is int and 0 <= selected < len(maps_list['list']) else -1

        for maps in maps_list['list']:
            self.addTab(maps, False)

        self.tab_widget.currentChanged.connect(self.changedTab)
        viewed = maps_list.get('viewed', self.default_tab_index)
        viewed = viewed if type(viewed) is int and 0 <= viewed < len(self.tabs) else self.default_tab_index
        self.changedTab(viewed)
        self.tab_widget.setCurrentIndex(viewed)

        self._initial_mapping_values = deepcopy(self.mapping_values())

        self._is_dirty = False

    def addTab(self, maps=None, forcus=True):
        if not self.current_model:
            QMessageBox.warning(self, tr("未选择笔记类型"), tr("请先在上方选择目标笔记类型。"))
            return

        i = len(self.tabs)
        if isinstance(maps, list):
            maps = {'fields': maps, 'name': _('CONFIG_INDEX') % (i + 1)}

        tab = TabContent(self.current_model, maps['fields'] if maps else None,
                         self.dict_services, self.controller, parent_dialog=self)
        self.tabs.append(tab)
        self.tab_widget.addTab(tab, maps['name'] if maps else _('CONFIG_INDEX') % (i + 1))
        star = QToolButton(self.tab_widget)
        star.setCheckable(True)
        star.setAutoRaise(True)
        star.setStyleSheet('QToolButton { border: none; background: transparent; padding: 0 3px; font-size: 17px; } QToolButton:checked { color: palette(highlight); }')
        star.setToolTip(tr('点亮星星，将此配置用于自动运行；每个笔记类型最多一个。'))
        star.clicked.connect(lambda checked, item=tab: self.toggle_auto_config(item))
        tab.auto_star = star
        self.tab_widget.tabBar().setTabButton(i, QTabBar.ButtonPosition.LeftSide, star)
        close = QToolButton(self.tab_widget)
        close.setText('×')
        close.setAutoRaise(True)
        close.setFixedSize(22, 22)
        close.setToolTip(tr('删除此配置'))
        close.setStyleSheet('QToolButton { border: none; background: transparent; color: palette(text); } QToolButton:hover { background: palette(midlight); }')
        close.clicked.connect(lambda checked=False, item=tab: self.removeTab(self.tabs.index(item)) if item in self.tabs else None)
        self.tab_widget.tabBar().setTabButton(i, QTabBar.ButtonPosition.RightSide, close)
        self.update_auto_stars()
        self._is_dirty = True

        if forcus:
            self.tab_widget.setCurrentIndex(i)

    def removeTab(self, i, forcus=False):
        if not forcus and len(self.tabs) <= 1:
            return
        tab = self.tabs[i]
        del self.tabs[i]
        self.tab_widget.removeTab(i)
        tab.destroy()
        self._is_dirty = True

        if self.default_tab_index == i:
            self.default_tab_index = 0
        elif self.default_tab_index > i:
            self.default_tab_index -= 1
        if self.auto_tab_index == i:
            self.auto_tab_index = -1
        elif self.auto_tab_index > i:
            self.auto_tab_index -= 1
        self.update_auto_stars()
        self.changedTab(self.tab_widget.currentIndex())

    def toggle_auto_config(self, tab):
        index = self.tabs.index(tab)
        self.auto_tab_index = index
        self.update_auto_stars()
        self._is_dirty = True

    def update_auto_stars(self):
        for index, tab in enumerate(self.tabs):
            star = getattr(tab, 'auto_star', None)
            if star is not None:
                star.setChecked(index == self.auto_tab_index)
                star.setText('★' if index == self.auto_tab_index else '☆')
                star.setAccessibleName(tr('自动运行配置'))

    def changedTab(self, i):
        if i >= 0 and i < len(self.tabs):
            self.tabs[i].build_layout()

    def ai_options_changed(self):
        self._is_dirty = True

    # =========================================================================
    # 第三部分：交互事件响应 (Events & Logic Routing)
    # =========================================================================
    def on_model_combo_changed(self, index):
        if self.save() is False:
            blocker = QSignalBlocker(self.model_combo)
            self.model_combo.setCurrentIndex(self.model_combo.findData(self.model_id))
            blocker.unblock()
            return
        new_id = self.model_combo.itemData(index)
        if new_id:
            self.model_id = new_id
            self.current_model = mw.col.models.get(new_id)
            self.build_tabs_layout()

    def update_log_btn_text(self):
        if self.controller.is_logging_enabled():
            self.log_toggle_btn.setText(tr('日志：开启'))
        else:
            self.log_toggle_btn.setText(tr('日志：关闭'))

    def toggle_logging(self):
        self.controller.toggle_logging()
        self.update_log_btn_text()

    def open_log_file(self):
        import os
        import tempfile
        log_path = os.path.join(tempfile.gettempdir(), 'FastCardMaker.log')
        if not os.path.exists(log_path):
            log_path = os.path.join(tempfile.gettempdir(), 'FastWordQuery.log')
        if os.path.exists(log_path):
            QDesktopServices.openUrl(QUrl.fromLocalFile(log_path))
        else:
            QMessageBox.information(self, tr("提示"), tr("尚未生成日志文件。\n请先开启日志，并在执行相关操作后再查看。"))

    def check_dict_status(self, hash_key=None, status=None):
        if self._closed or not hasattr(self, 'dict_services'): return
        from ..service.base import LocalService
        for service in self.dict_services.get('local', []):
            key = LocalService.builder_key(service['path']) if service.get('path') else service['unique']
            if key == hash_key or service['unique'] == hash_key:
                service['status'] = status or LocalService.get_db_status(service['path'])
        for tab in self.tabs:
            tab.refresh_dict_combos(self.dict_services)

    def show_paras(self):
        if self.save() is False:
            return
        dialog = SettingDialog(self, _('SETTINGS'))
        dialog.exec()
        if dialog.configuration_loaded:
            self._is_dirty = False
            self.dict_services = self.controller.preview_services()
            self.build_tabs_layout()
            self.update_log_btn_text()
            self._updater.request()
        dialog.destroy()

    def retry_dictionaries(self):
        from ..service.base import LocalService
        for service in self.dict_services.get('local', []):
            if service.get('status') == 'failed' and service.get('path'):
                LocalService.retry_build(service['path'])

    def show_ai_settings(self):
        from .script_compare import check_scripts
        if not check_scripts(self):
            return
        from .ai_settings import AISettingsDialog
        from ..service.ai_config import profile_choices
        dialog = AISettingsDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.dict_services['ai'] = profile_choices()
            for tab in self.tabs:
                tab.refresh_dict_combos(self.dict_services)
        dialog.deleteLater()

    def show_fm_dialog(self):
        if self.save() is False:
            return
        self.done(1001)

    def show_dm_dialog(self):
        if self.save() is False:
            return
        self.done(1002)

    def show_about(self):
        from .common import show_about_dialog
        show_about_dialog(self)

    def save(self):
        if not self.current_model:
            return
        maps_list = {'list': [], 'def': self.default_tab_index, 'auto': self.auto_tab_index,
                     'viewed': self.tab_widget.currentIndex()}
        automatic = getattr(config, 'auto_run', {})
        if (isinstance(automatic, dict) and automatic.get('enabled')
                and str(self.current_model['id']) in {str(value) for value in automatic.get('model_ids', [])}
                and self.auto_tab_index < 0):
            QMessageBox.warning(self, tr('自动运行配置'), tr('请先为参与自动运行的笔记类型点亮一个配置星星。'))
            return False
        for i, tab in enumerate(self.tabs):
            maps_list['list'].append({
                'fields': tab.data,
                'name': self.tab_widget.tabBar().tabText(i)
            })
        from ..service.ai_validation import validate_ai_mappings
        try:
            names = [field['name'] for field in self.current_model['flds']]
            for tab_data in maps_list['list']:
                validate_ai_mappings(tab_data['fields'] or [], names)
        except ValueError as error:
            QMessageBox.warning(self, tr('AI 提示词错误'), str(error))
            return False
        self.controller.save_config(self.current_model, maps_list)
        for tab in self.tabs:
            tab.commit_mapping()
        self._is_dirty = False
        self._initial_mapping_values = deepcopy(self.mapping_values())

    def mapping_values(self):
        return {'def': self.default_tab_index, 'auto': self.auto_tab_index,
                'list': [{'name': self.tab_widget.tabText(i), 'fields': tab.data} for i, tab in enumerate(self.tabs)]}

    def accept(self):
        if self.save() is False:
            return
        self.done(QDialog.DialogCode.Accepted)
