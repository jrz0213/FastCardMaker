"""Manage AI profiles and locally persisted API keys."""

from ...translations import text as tr

from aqt.qt import *

from ..base import Dialog
from .layout import build_settings_layout
from ...service.ai_config import PRESETS, new_profile, profiles, save_profiles, session_key
import json
from ...service.ai_support.parameters import parameters_for, defaults as parameter_defaults, endpoint
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
            self.list.addItem(item['name'])
        if self.items:
            self.list.setCurrentRow(0)
        else:
            self.add_profile()

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
            self.list.item(self.current).setText(text.strip() or tr('未命名'))

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
        self.list.item(self.current).setText(item['name'] or tr('未命名'))

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
        address = self.address.text().strip().rstrip('/')
        for suffix, mode in (('/chat/completions', 'chat'), ('/responses', 'responses')):
            if address.endswith(suffix):
                self.mode.setCurrentIndex(self.mode.findData(mode))
                break

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
            old_suffix = '/responses' if previous == 'responses' else '/chat/completions'
            if self.address.text().rstrip('/').endswith(old_suffix):
                self.address.setText(self.address.text().rstrip('/')[:-len(old_suffix)] +
                                     ('/responses' if mode == 'responses' else '/chat/completions'))
        self._parameter_mode = mode
        notes = {
            'deepseek': tr('DeepSeek：Chat 使用 thinking.type；Responses 使用 reasoning.effort。'),
            'qwen': tr('百炼 Chat：enable_thinking=false 关闭思考；其他接口请按服务文档修改。'),
            'gemini': tr('Gemini 兼容 Chat：reasoning_effort=none；部分模型不能关闭思考，请自行修改。'),
            'claude': tr('Claude：thinking.type=disabled 是示例；官方 Messages 接口不支持，请填写 Chat 兼容网关地址。'),
        }
        self.hint.setText(notes.get(provider, tr('Responses 使用 reasoning.effort；Chat 使用 reasoning_effort。')) +
                          '\n' + tr('预填温度 1、关闭思考的示例。不同模型支持范围不同，可自由增删；JSON 中不要写备注。限速、重试及超时在插件设置的 AI 设置中调整。'))

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
        self.capture()
        try:
            save_profiles(self.items, self.keys)
        except ValueError as error:
            self.details.setChecked(True)
            self.parameters.setFocus()
            QMessageBox.warning(self, tr('AI 配置未保存'), str(error))
            return
        super().accept()
