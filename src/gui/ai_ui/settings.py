"""Manage AI profiles and locally persisted API keys."""

from ...translations import text as tr

from aqt.qt import *

from ..base import Dialog
from .layout import build_settings_layout
from ...service.ai_config import PRESETS, new_profile, profiles, save_profiles, session_key
import json
from ...service.ai_support.parameters import parameters_for, defaults as parameter_defaults, endpoint, protocol
from ...service.ai_keys import key_store_path


class AISettingsDialog(Dialog):
    def __init__(self, parent):
        super().__init__(parent, tr('AI 设置'))
        self.resize(980, 700)
        self.items = profiles()
        try:
            self.keys = {item['id']: session_key(item['id']) for item in self.items}
        except ValueError as error:
            QMessageBox.warning(self, tr('API Key 读取失败'), str(error))
            self.keys = {}
        self.current = -1
        build_settings_layout(self)
        for item in self.items:
            self.list.addItem(item['name'] + ('' if self.keys.get(item['id']) else ' (' + tr('缺失 API Key') + ')'))
        if self.items:
            self.list.setCurrentRow(0)
        else:
            self.add_profile()
        self.watch_changes(self.current_values)
        self.key.textChanged.connect(lambda *_: self.update_name(self.name.text()))
        self.update_name(self.name.text())

    def current_values(self):
        from copy import deepcopy
        self.capture()
        return deepcopy((self.items, self.keys))

    def open_settings_folder(self):
        try:
            folder = key_store_path().parent
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError()
        except OSError:
            QMessageBox.warning(self, tr('提示'), tr('无法打开配置目录，请检查文件夹权限。'))

    def toggle_details(self, expanded):
        self.advanced.setVisible(expanded)
        self.details.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        if expanded:
            self._collapsed_height = self.height()
            available = self.screen().availableGeometry().height() - 40
            self.resize(self.width(), max(self.height(), min(available,
                        self.height() + self.advanced.sizeHint().height())))
        elif hasattr(self, '_collapsed_height'):
            self.resize(self.width(), self._collapsed_height)

    def update_name(self, text):
        if self.current >= 0:
            self.list.item(self.current).setText((text.strip() or tr('未命名')) +
                ('' if self.key.text().strip() else ' (' + tr('缺失 API Key') + ')'))

    def capture(self):
        if self.current < 0:
            return
        item = self.items[self.current]
        item.update(name=self.name.text().strip(), provider=self.provider.currentData(),
                    base_url=self.address.text().strip(),
                    model=self.model.text().strip(), mode=self.mode.currentData(),
                    parameters=self.parameters.toPlainText(), endpoint_url=True,
                    skill=self.skill.toPlainText(), send_mode=self.send_mode.currentData())
        item.pop('max_tokens', None)
        self.keys[item['id']] = self.key.text().strip()
        self.update_name(item['name'])

    def select_profile(self, index):
        self.capture()
        self.current = index
        if index < 0:
            return
        item = self.items[index]
        self.loading = True
        blocker = QSignalBlocker(self.provider)
        self.provider.setCurrentIndex(max(0, self.provider.findData(item['provider'])))
        blocker.unblock()
        for widget, key in [(self.name, 'name'), (self.address, 'base_url')]:
            widget.setText(endpoint(item) if key == 'base_url' else item.get(key, ''))
        self.model.set_provider(item['provider'], item.get('model', ''))
        self.key.setText(self.keys.get(item['id'], ''))
        self.mode.setCurrentIndex(max(0, self.mode.findData(item['mode'])))
        self.send_mode.setCurrentIndex(max(0, self.send_mode.findData(item.get('send_mode', 'field'))))
        params = item['parameters'] if 'parameters' in item else parameters_for(item)
        self.parameters.setPlainText(params if isinstance(params, str) else json.dumps(params, ensure_ascii=False, indent=2))
        self.skill.setPlainText(item.get('skill', ''))
        self._parameter_mode = self.mode.currentData()
        self.loading = False
        self.refresh_options()

    def address_edited(self):
        try:
            mode = protocol(dict(base_url=self.address.text().strip(), endpoint_url=True))
        except ValueError:
            return  # Report incomplete/unsupported addresses when saving.
        self.mode.setCurrentIndex(self.mode.findData(mode))

    def refresh_options(self, *_):
        if self.loading:
            return
        provider = self.provider.currentData()
        mode = self.mode.currentData()
        previous = getattr(self, '_parameter_mode', mode)
        if previous != mode:
            try:
                current = json.loads(self.parameters.toPlainText())
            except ValueError:
                current = None
            if current == parameter_defaults(provider, previous):
                self.parameters.setPlainText(json.dumps(parameter_defaults(provider, mode), ensure_ascii=False, indent=2))
        self._parameter_mode = mode
        notes = {
            'deepseek': tr('DeepSeek：Chat 使用 thinking.type；Responses 使用 reasoning.effort。'),
            'qwen': tr('Qwen 默认使用 Responses；enable_thinking=false 关闭思考。百炼地域或业务空间可能使用专属域名，请填写控制台对应的完整地址。'),
            'gemini': tr('Gemini 默认使用官方 Interactions；generation_config 中填写 temperature 和 thinking_level。minimal 不等于关闭思考，支持范围取决于模型。'),
            'claude': tr('Claude 默认使用官方 Messages；max_tokens 是输出上限，thinking.type=disabled 是关闭思考的示例。'),
        }
        self.hint.setText(notes.get(provider, tr('Responses 使用 reasoning.effort；Chat 使用 reasoning_effort。')) +
                          '\n' + tr('预填参数仅为示例，不同模型支持范围不同，可自由增删；JSON 中不要写备注。限速、重试及超时在插件设置的 AI 设置中调整。'))

    def apply_preset(self):
        self.loading = True
        name, address, mode = PRESETS[self.provider.currentData()]
        self.name.setText(name)
        self.address.setText(address)
        self.model.set_provider(self.provider.currentData())
        # A provider change must never reuse the previous provider's credential.
        self.key.clear()
        self.mode.setCurrentIndex(self.mode.findData(mode))
        self.parameters.setPlainText(json.dumps(parameter_defaults(self.provider.currentData(), mode), ensure_ascii=False, indent=2))
        self._parameter_mode = mode
        self.loading = False
        self.refresh_options()

    def add_profile(self):
        self.capture()
        item = new_profile()
        self.items.append(item)
        self.list.addItem(item['name'])
        self.list.setCurrentRow(len(self.items) - 1)

    def remove_profile(self):
        index = self.current
        if index < 0:
            return
        blocker = QSignalBlocker(self.list)
        self.keys.pop(self.items[index]['id'], None)
        del self.items[index]
        self.list.takeItem(index)
        self.current = -1
        blocker.unblock()
        if self.items:
            self.list.setCurrentRow(min(index, len(self.items) - 1))
            if self.current < 0:
                self.select_profile(self.list.currentRow())
        else:
            for widget in (self.name, self.address, self.key):
                widget.clear()
            self.model.setText('')
            self.skill.clear()

    def accept(self):
        self.address_edited()
        self.capture()
        try:
            save_profiles(self.items, self.keys)
        except ValueError as error:
            self.details.setChecked(True)
            self.parameters.setFocus()
            QMessageBox.warning(self, tr('AI 配置未保存'), str(error))
            return
        super().accept()
