"""Three-entry MDX source analysis, preview and explicit script saving."""
import json
from html import escape
import os
import time
import traceback
import uuid
from datetime import datetime, timezone
from hashlib import sha256
from copy import deepcopy
from dataclasses import replace

from aqt.qt import *
from ..translations import text as tr
from ..utils.media import profile_token
from ..service.ai import request_ai_text, request_payload, snapshot_connection, AIError
from ..service.ai_config import profile_choices, validate_profile
from ..service.selector_scripts import (collect_samples, build_prompt, parse_rules,
                                        validate_samples, render_script, save_script, INSTRUCTIONS, REQUIREMENTS_LIMIT,
                                        DEFAULT_SAMPLE_WORDS)
from ..service.dictionary_assets import collect_javascript
from ..service.script_updates import (original_scripts, script_payload, update_source, replace_script,
                                     dictionary_identity, history_directory, trash_directory,
                                     write_conversation, restore_script)
from pathlib import Path
from .base import Dialog
from .service_loader import ServiceLoaderThread
from .flow_layout import FlowLayout
from ..service.script_information import request_record, redact, compact_history, portable_markdown, load_history, history_sessions, debug_feedback
from ..service.script_debug import debug_exports
from ..service.python_scripts import PYTHON_INSTRUCTIONS, parse_python
from ..service.script_reply import reply_content, display_reply
from .script_message_view import stylesheet as message_stylesheet, render_body

DEFAULT_COMMAND = '提取词典已有的释义、音标、例句和发音。结合 HTML、JS 和原脚本分析结构；仅在需要时修复音频路径，保留已正常工作的处理。不要添加无关字段；无法确定的内容不要猜测。'


CHAT_INSTRUCTIONS = INSTRUCTIONS


class ScriptOperationThread(ServiceLoaderThread):
    prepared = pyqtSignal(dict)

    def __init__(self, controller):
        super().__init__(controller)
        controller.on_prepared = self.prepared.emit


class Generation:
    def __init__(self, path, unique, words, names, command='', attachments=None, script_paths=None, class_name=None,
                 history=None, message='', current=None, debug=False, record_directory=None, debug_result=None, session_id=None,
                 return_json=True, local_information=None):
        self.path, self.unique, self.words, self.names = path, unique, words, names
        self.command, self.message = command, message
        self.history, self.current = deepcopy(history or []), deepcopy(current)
        self.local_information = deepcopy(local_information or [])
        self.debug, self.debug_result = debug, deepcopy(debug_result)
        self.record_directory, self.on_prepared = record_directory, None
        self.session_id = session_id
        self.return_json = return_json
        selected = attachments if attachments is not None else {'html': True, 'js': True, 'script': True}
        self.attachments = {key: bool(selected.get(key, False)) for key in ('html', 'js', 'script')}
        self.script_paths, self.class_name = list(script_paths or []), class_name
        self.connection = snapshot_connection(unique)
        if self.connection.profile is not None:
            self.connection = replace(self.connection, profile=dict(self.connection.profile, skill=''))

    def _record(self, record):
        record = redact(record, self.connection.key)
        record.setdefault('id', uuid.uuid4().hex)
        if self.session_id:
            record['session_id'] = self.session_id
        record.setdefault('time', datetime.now(timezone.utc).isoformat())
        record.pop('storage_saved', None)
        return record

    def load_services(self, cancelled=None, progress=None):
        from ..service.base import MdxService, LocalService
        from ..service.local import DictionaryNotReady
        record = None
        debug_record = None
        try:
            if self.connection.profile is None:
                raise AIError(tr('AI 配置已删除，请重新选择。'))
            validate_profile(self.connection.profile)
            if not self.connection.key:
                raise AIError(tr('未填写 API Key，请打开 AI 设置。'))
            if not any(self.attachments.values()) and not self.message:
                raise ValueError(tr('请至少勾选一种发送内容。'))
            service = MdxService(self.path)
            if not service.support:
                raise ValueError(tr('词典文件不存在，请先恢复路径。'))
            deadline = time.monotonic() + 90
            while service.builder is None:
                if cancelled and cancelled():
                    return {}
                status = LocalService.get_db_status(self.path)
                if status == 'failed' or time.monotonic() >= deadline:
                    raise DictionaryNotReady(status)
                time.sleep(0.1)
                service.builder = LocalService._get_builder(self.path)
            samples = collect_samples(service.builder, self.words, cancelled)
            originals = original_scripts(self.script_paths)
            javascript = collect_javascript(samples, service.builder, self.path, cancelled) if self.attachments['js'] else []
            if not self.message and not (self.attachments['html'] or self.attachments['js'] and any('content' in item for item in javascript)
                                        or self.attachments['script'] and originals):
                raise ValueError(tr('勾选的内容均未找到，未发送请求。'))
            prompt_data = json.loads(build_prompt(samples, self.names, javascript, self.command,
                                      script_payload(originals) if self.attachments['script'] else [], self.attachments['html']))
            from ..service.dictionary_binding import descriptor
            prompt_data['dictionary'] = dict(descriptor(self.path), filename=Path(self.path).name)
            prompt_data['output_format'] = 'json_rules' if self.return_json else 'python'
            prompt_data['attachments'] = dict(self.attachments, original_script_found=bool(originals),
                                               javascript_found=any('content' in item for item in javascript))
            if self.message:
                prompt_data['user_message'] = self.message
                if self.debug_result:
                    prompt_data['latest_debug'] = debug_feedback(self.debug_result)
            if self.current:
                prompt_data['current_rules'] = self.current['rules']
                if self.attachments['script']:
                    source = self.current['source']
                    prompt_data['current_script'] = {'name': self.current['filename'],
                        'source': source[:60000] if self.return_json else source,
                        'truncated': self.return_json and len(source) > 60000}
                    if not self.return_json:
                        prompt_data['code'] = source
            elif not self.return_json and self.attachments['script'] and originals:
                prompt_data['code'] = originals[0]['source']
            if self.local_information:
                prompt_data['local_information'] = deepcopy(self.local_information)
            from ..service.script_information import deduplicate_scripts
            prompt_data = deduplicate_scripts(prompt_data, self.history)
            prompt_data = redact(prompt_data, self.connection.key)
            from ..service.script_information import hide_local_paths
            prompt_data = hide_local_paths(prompt_data, self.path)
            prompt = json.dumps(prompt_data, ensure_ascii=False)
            instructions = (CHAT_INSTRUCTIONS if self.message else INSTRUCTIONS) if self.return_json else PYTHON_INSTRUCTIONS
            history = hide_local_paths(redact(self.history, self.connection.key), self.path)
            payload = request_payload(self.connection.profile, prompt, instructions, history=history)
            record = request_record(self.connection.profile.get('model', ''), instructions, prompt_data, payload,
                                    self.message or self.command, dictionary_identity(self.path))
            record['context'] = {'history_messages': len(history), 'request_characters': len(json.dumps(payload, ensure_ascii=False)),
                                 'attachments_not_repeated_in_history': True}
            record = self._record(record)
            if self.on_prepared:
                self.on_prepared(deepcopy(record))
            if progress:
                progress(1, 2)
            response = request_ai_text(self.unique, prompt, instructions, cancelled=cancelled,
                                       connection=self.connection, history=history)
            record['response'] = redact(response, self.connection.key)
            if cancelled and cancelled():
                record['state'] = 'cancelled'
                return {'record': self._record(record)}
            response, chat_only = reply_content(response, self.return_json)
            if chat_only:
                record['state'] = 'completed'
                return {'record': self._record(record), 'chat_only': True}
            if not self.return_json:
                try:
                    source, generated_class = parse_python(response, self.class_name)
                except (ValueError, SyntaxError):
                    if self.message and not response.lstrip().startswith(('```', 'from ', 'import ', '#', 'class ', '@')):
                        record['state'] = 'completed'
                        return {'record': self._record(record), 'chat_only': True}
                    raise
                original = originals[0] if originals else None
                filename = Path(original['path']).name if original else 'fcm_ai_' + dictionary_identity(self.path) + '.py'
                result = {'samples': samples, 'javascript': javascript, 'prompt': prompt,
                          'rules': {'fields': [], 'unavailable': []}, 'preview': [], 'filename': filename,
                          'source': source, 'original': original, 'format': 'python', 'class_name': generated_class}
                record['state'], record['local'] = 'completed', {'validation': 'syntax_and_structure_only',
                                                               'generated_script': source, 'filename': filename}
                result['record'] = self._record(record)
                return result
            if self.message and not response.lstrip().startswith(('{', '```')):
                record['state'], record['local'] = 'completed', {'message': tr('AI 已回复，未修改当前脚本。')}
                return {'record': self._record(record), 'chat_only': True}
            rules = parse_rules(response, self.names)
            if not rules['fields'] and 'media' in rules and not rules['media']:
                record['state'] = 'completed'
                record['local'] = {'message': tr('无需修改，保留原脚本。')}
                return {'record': self._record(record), 'chat_only': True}
            original = originals[0] if originals else None
            if original:
                filename = Path(original['path']).name
                source = update_source(original['source'], rules, self.class_name)
            else:
                filename, source = render_script(self.path, rules)
            result = {'samples': samples, 'javascript': javascript, 'prompt': prompt,
                      'rules': rules, 'preview': [], 'filename': filename, 'source': source, 'original': original}
            record['local'] = {'generated_script': source, 'filename': filename}
            try:
                result['preview'] = validate_samples(samples, rules, service.builder, self.path)
            except Exception:
                if self.debug:
                    debug_record = self._record(debug_exports(service, result, cancelled, self.class_name))
                raise
            record['state'], record['local'] = 'completed', {'validation': 'passed', 'fields': [r['name'] for r in rules['fields']],
                                                            'generated_script': source, 'filename': filename}
            result['record'] = self._record(record)
            if self.debug:
                report = debug_exports(service, result, cancelled, self.class_name)
                result['debug_record'] = self._record(report)
            return result
        except Exception as error:
            detail = {'error_type': type(error).__name__, 'error': str(error), 'traceback': traceback.format_exc()}
            if isinstance(error, AIError):
                detail['error_code'] = error.code
            if record:
                record.update(state='failed', error=str(error), local={**record.get('local', {}), **detail})
                record = self._record(record)
            else:
                record = self._record(dict(kind='local', dictionary_id=dictionary_identity(self.path), **detail))
            value = {'error': redact(str(error), self.connection.key), 'record': record}
            if debug_record:
                value['debug_record'] = debug_record
            return value


class DebugOperation:
    def __init__(self, path, result, class_name=None, record_directory=None, words=None, session_id=None):
        self.path, self.result, self.class_name = path, deepcopy(result), class_name
        self.words = words
        self.session_id = session_id
        self.record_directory, self.on_prepared = record_directory, None

    def load_services(self, cancelled=None, progress=None):
        from ..service.base import MdxService, LocalService
        try:
            service = MdxService(self.path)
            if not service.support:
                raise FileNotFoundError('Dictionary file is unavailable')
            deadline = time.monotonic() + 90
            while service.builder is None:
                if cancelled and cancelled():
                    return {}
                if time.monotonic() >= deadline or LocalService.get_db_status(self.path) == 'failed':
                    raise ValueError('Dictionary index is unavailable')
                time.sleep(0.1)
                service.builder = LocalService._get_builder(self.path)
            if self.words is not None:
                self.result['samples'] = collect_samples(service.builder, self.words, cancelled)
            report = debug_exports(service, self.result, cancelled, self.class_name)
        except Exception as error:
            report = {'kind': 'debug', 'dictionary_id': dictionary_identity(self.path), 'passed': False,
                      'id': uuid.uuid4().hex, 'time': datetime.now(timezone.utc).isoformat(),
                      'source_sha256': sha256(self.result.get('source', '').encode()).hexdigest(),
                      'error': str(error), 'error_type': type(error).__name__, 'traceback': traceback.format_exc()}
        if self.session_id:
            report['session_id'] = self.session_id
        return {'debug_record': report}


class HistoryOperation:
    def __init__(self, directory, path, session_id=None):
        self.directory, self.path, self.on_prepared = directory, path, None
        self.session_id = session_id

    def load_services(self, cancelled=None, progress=None):
        identity = dictionary_identity(self.path)
        if self.session_id is None:
            return {'history_sessions': history_sessions(self.directory, identity, cancelled=cancelled)}
        return {'history_records': load_history(self.directory, identity, cancelled=cancelled, session_id=self.session_id),
                'import_session': self.session_id}


class ScriptGeneratorDialog(Dialog):
    saved = pyqtSignal(str)

    def __init__(self, parent, dict_path, script_paths=None, class_name=None):
        super().__init__(parent, tr('AI 生成词典脚本'))
        self.dict_path, self.token = dict_path, profile_token()
        from ..service.script_library import script_directory
        self.script_directory = str(script_directory())
        if script_paths is None:
            fingerprint = dictionary_identity(dict_path)
            script_paths = sorted((path for prefix in ('fcm_ai_', 'fwq_ai_')
                                   for path in Path(self.script_directory).glob(prefix + fingerprint + '*.py')),
                                  key=lambda path: path.stat().st_mtime, reverse=True)
        self.script_paths, self.class_name = [str(path) for path in script_paths], class_name
        self.loader = None
        self.result = None
        self._editing_path = None
        self._editing_source = None
        self._result_saved = False
        self.conversations = []
        self.session_id = uuid.uuid4().hex
        self.imported_sessions = set()
        self._pending_import = None
        self._expanded_messages = set()
        self._selected_messages = set()
        self._message_contents = {}
        self.last_debug = None
        self._secret_values = set()
        self._operation_kind = 'generate'
        self._closed = False
        self.resize(820, 650)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.profile_combo = QComboBox()
        for profile in profile_choices():
            self.profile_combo.addItem(profile['title'], profile['unique'])
        form.addRow(tr('AI 配置'), self.profile_combo)
        words = QWidget()
        word_layout = QHBoxLayout(words)
        word_layout.setContentsMargins(0, 0, 0, 0)
        self.words = []
        for word, category in zip(DEFAULT_SAMPLE_WORDS, (tr('名词'), tr('动词'), tr('形容词'))):
            edit = QLineEdit()
            edit.setText(word)
            edit.setPlaceholderText(tr('留空自动抽样'))
            edit.setToolTip(category + ' · ' + word + '\n' + tr('默认词缺失时自动使用备选样本；自行改词后按填写内容查找。'))
            self.words.append(edit)
            word_layout.addWidget(edit)
        form.addRow(tr('三个样本词'), words)
        self.command = QPlainTextEdit()
        self.command.setPlainText(tr(DEFAULT_COMMAND))
        self.command.setPlaceholderText(tr('描述希望提取或修复的内容，留空使用默认要求。'))
        self.command.setMinimumHeight(75)
        self.command.setMaximumHeight(100)
        self.command.setInputMethodHints(Qt.InputMethodHint.ImhNone)
        form.addRow(tr('命令'), self.command)
        attachment_row = QWidget()
        attachment_layout = QHBoxLayout(attachment_row)
        attachment_layout.setContentsMargins(0, 0, 0, 0)
        self.attachments = {}
        for key, label in (('html', tr('发送 HTML')), ('js', tr('发送 JS')), ('script', tr('发送原脚本'))):
            checkbox = QCheckBox(label)
            checkbox.setChecked(True)
            checkbox.setToolTip(tr('未找到的附件不会发送；JS 和原脚本去重后只发送一次。'))
            self.attachments[key] = checkbox
            attachment_layout.addWidget(checkbox)
        self.return_json = QCheckBox(tr('使用规则模式'))
        self.return_json.setChecked(True)
        self.return_json.setToolTip(tr('勾选：返回 ai-message 和 rules；取消：返回 ai-message 和完整 code。只有消息时不修改脚本。'))
        attachment_layout.addWidget(self.return_json)
        output_help = QToolButton()
        output_help.setText('?')
        output_help.setAutoRaise(True)
        output_help.setAccessibleName(tr('输出方式说明'))
        output_help.setToolTip(tr('查看 JSON 规则与直接生成 Python 的区别'))
        output_help.clicked.connect(self.show_output_help)
        attachment_layout.addWidget(output_help)
        attachment_layout.addStretch()
        form.addRow(tr('发送内容'), attachment_row)
        layout.addLayout(form)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        tabs = self.tabs = QTabWidget()
        self.preview, self.samples_view, self.source_view = QPlainTextEdit(), QPlainTextEdit(), QPlainTextEdit()
        information = QWidget()
        information_layout = QVBoxLayout(information)
        information_layout.setContentsMargins(0, 0, 0, 0)
        self.conversation = QTextBrowser()
        self.conversation.setOpenExternalLinks(False)
        self.conversation.setOpenLinks(False)
        self.conversation.anchorClicked.connect(self.toggle_message)
        information_layout.addWidget(self.conversation, 1)
        copies = QHBoxLayout()
        self.copy_current = QPushButton(tr('复制选中内容'))
        self.copy_current.clicked.connect(self.copy_selected_information)
        copy_all = QPushButton(tr('复制全部'))
        copy_all.clicked.connect(lambda: self.copy_information(all_records=True))
        export = QPushButton(tr('导出 Markdown'))
        export.clicked.connect(self.export_information)
        import_chat = QPushButton(tr('导入对话'))
        import_chat.clicked.connect(self.import_conversation)
        for button in (self.copy_current, copy_all, export, import_chat):
            copies.addWidget(button)
        information_layout.addLayout(copies)
        for label, widget in ((tr('提取预览'), self.preview), (tr('词条源码'), self.samples_view),
                              (tr('生成脚本'), self.source_view), (tr('信息历史'), information)):
            if isinstance(widget, QPlainTextEdit):
                widget.setReadOnly(True)
            tabs.addTab(widget, label)
        layout.addWidget(tabs, 1)
        chat = QGroupBox(tr('继续对话'))
        chat_layout = QVBoxLayout(chat)
        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText(tr('例如：根据最近的调试错误修复发音；或者解释当前提取规则。'))
        self.chat_input.setMaximumHeight(65)
        chat_layout.addWidget(self.chat_input)
        chat_options = QHBoxLayout()
        self.send_history = QRadioButton(tr('携带全部消息'))
        self.send_history.setChecked(True)
        self.send_selected = QRadioButton(tr('携带勾选的消息'))
        self.history_mode = QButtonGroup(self)
        self.history_mode.addButton(self.send_history)
        self.history_mode.addButton(self.send_selected)
        self.send_message = QPushButton(tr('发送消息'))
        self.send_message.clicked.connect(self.begin_chat)
        for widget in (self.send_history, self.send_selected, self.send_message):
            chat_options.addWidget(widget)
        chat_layout.addLayout(chat_options)
        information_layout.addWidget(chat)
        action_bar = QWidget()
        actions = FlowLayout(action_bar)
        self.generate = QPushButton(tr('发送三个词条并生成'))
        self.generate.clicked.connect(self.begin)
        self.save_button = QPushButton(tr('保存脚本'))
        self.save_button.setEnabled(False)
        self.save_button.clicked.connect(self.save)
        self.debug_button = QPushButton(tr('调试'))
        self.debug_button.setEnabled(False)
        self.debug_button.clicked.connect(self.begin_debug)
        self.edit_script_button = QPushButton(tr('编辑脚本'))
        self.edit_script_button.clicked.connect(self.edit_script)
        for button in (self.generate, self.debug_button, self.save_button, self.edit_script_button):
            actions.addWidget(button)
        restore = self.restore_button = QPushButton(tr('恢复旧脚本'))
        restore.clicked.connect(self.restore_old_script)
        self.load_history_button = QPushButton(tr('导入之前的会话'))
        self.load_history_button.clicked.connect(self.begin_history)
        self.load_history_button.hide()
        actions.addWidget(restore)
        layout.addWidget(action_bar)

    def begin(self, *_):
        self._begin_request()

    def begin_chat(self):
        message = self.chat_input.toPlainText().strip()
        if not message:
            self.status.setText(tr('请先填写要发送的消息。'))
            return
        if len(message) > REQUIREMENTS_LIMIT:
            self.status.setText(tr('消息最多填写 4000 个字符。'))
            return
        self._begin_request(message)

    def _begin_request(self, message=''):
        if self.loader:
            return
        if not self.sync_edited_script():
            return
        unique = self.profile_combo.currentData()
        words = [edit.text().strip() for edit in self.words]
        command = self.command.toPlainText().strip()
        if len(command) > REQUIREMENTS_LIMIT:
            self.status.setText(tr('命令最多填写 4000 个字符。'))
            return
        if not unique or any(words) and (not all(words) or len({word.casefold() for word in words}) != 3):
            self.status.setText(tr('请选择 AI 配置；样本词填写三个不同的词，或全部留空。'))
            return
        if self.token != profile_token():
            self.status.setText(tr('用户已切换，请重新打开生成窗口。'))
            return
        command = command or tr(DEFAULT_COMMAND)
        if tuple(word.casefold() for word in words) == DEFAULT_SAMPLE_WORDS:
            words = []
        attachments = {key: checkbox.isChecked() for key, checkbox in self.attachments.items()}
        if not any(attachments.values()) and not message:
            self.status.setText(tr('请至少勾选一种发送内容。'))
            return
        self._operation_kind = 'chat' if message else 'generate'
        operation = Generation(self.dict_path, unique, words, None, command, attachments,
                               self.script_paths, self.class_name,
                               history=self.selected_history(),
                               message=message, current=self.result, debug=False,
                               record_directory=None,
                               debug_result=None, session_id=self.session_id,
                               return_json=self.return_json.isChecked(), local_information=self.selected_local_information())
        self._secret_values.add(operation.connection.key)
        loader = self.loader = ScriptOperationThread(operation)
        loader.prepared.connect(self.request_started)
        loader.finished_signal.connect(self.ready)
        loader.failed.connect(self.failed)
        loader.progress.connect(lambda *_: self.status.setText(tr('三个词条已读取，正在等待 AI 分析…')) if not self._closed else None)
        loader.finished.connect(self.finished_loading)
        self.generate.setEnabled(False)
        self.edit_script_button.setEnabled(False)
        self.save_button.setEnabled(False)
        self.debug_button.setEnabled(False)
        self.send_message.setEnabled(False)
        self.restore_button.setEnabled(False)
        for widget in [self.profile_combo, self.command, self.return_json, *self.words, *self.attachments.values()]:
            widget.setEnabled(False)
        self.status.setText(tr('正在后台读取词条，首次建库可能需要等待…'))
        loader.start()

    def request_started(self, record):
        if self._closed or self.token != profile_token():
            return
        self.add_information(record)
        context = record.get('context', {})
        self.status.setText(tr('正在等待 AI；携带 %s 条历史消息，请求正文约 %s 个字符（字符数不是 Token 数）。') %
                            (context.get('history_messages', 0), context.get('request_characters', 0)))

    def begin_debug(self):
        if self.loader or not self.result or self.token != profile_token():
            return
        if not self.sync_edited_script():
            return
        words = [edit.text().strip() for edit in self.words]
        if any(words) and (not all(words) or len({word.casefold() for word in words}) != 3):
            self.status.setText(tr('请选择 AI 配置；样本词填写三个不同的词，或全部留空。'))
            return
        if tuple(word.casefold() for word in words) == DEFAULT_SAMPLE_WORDS:
            words = []
        self._operation_kind = 'debug'
        self.edit_script_button.setEnabled(False)
        loader = self.loader = ScriptOperationThread(DebugOperation(self.dict_path, self.result, self.class_name, None, words=words, session_id=self.session_id))
        loader.finished_signal.connect(self.ready)
        loader.failed.connect(self.failed)
        loader.finished.connect(self.finished_loading)
        for button in (self.generate, self.debug_button, self.save_button, self.send_message, self.restore_button):
            button.setEnabled(False)
        self.status.setText(tr('正在调试三个样本，媒体写入临时目录…'))
        loader.start()

    def cancel_operation(self):
        if self.loader:
            self.loader.stop()
            for value in reversed(self.conversations):
                if value.get('state') == 'sending':
                    record = dict(value, state='cancelled')
                    record.pop('storage_saved', None)
                    self.add_information(record)
                    break
            self.status.setText(tr('已请求取消；已发出的 AI 请求需要返回或超时，迟到结果不会应用。'))

    def begin_history(self, *_, session_id=None):
        if self.loader or self.token != profile_token():
            return
        self._operation_kind = 'history'
        loader = self.loader = ScriptOperationThread(HistoryOperation(self.script_directory, self.dict_path, session_id))
        loader.finished_signal.connect(self.ready)
        loader.failed.connect(self.failed)
        loader.finished.connect(self.finished_loading)
        self.generate.setEnabled(False)
        self.send_message.setEnabled(False)
        loader.start()

    def _start_pending_import(self):
        if self._pending_import and not self.loader and not self._closed:
            selected_id, self._pending_import = self._pending_import, None
            self.begin_history(session_id=selected_id)

    def add_information(self, record):
        record = deepcopy(record)
        for secret in self._secret_values:
            record = redact(record, secret)
        record.setdefault('id', uuid.uuid4().hex)
        record.setdefault('kind', 'request' if 'request' in record else 'local')
        record.setdefault('time', datetime.now(timezone.utc).isoformat())
        record.setdefault('dictionary_id', dictionary_identity(self.dict_path))
        record.setdefault('session_id', self.session_id)
        existing = next((i for i, value in enumerate(self.conversations) if value.get('id') == record['id']), None)
        if existing is None:
            self.conversations.append(record)
        else:
            self.conversations[existing] = record
        warning = record.get('record_warning', '')
        self.render_conversation()
        return warning

    def render_conversation(self):
        if self._closed:
            return
        scrollbar = self.conversation.verticalScrollBar()
        follow = scrollbar.maximum() - scrollbar.value() < 30
        position = scrollbar.value()
        dark = self.palette().color(QPalette.ColorRole.Base).lightness() < 128
        self.conversation.document().setDefaultStyleSheet(message_stylesheet(dark))
        colors = {'user': '#80b8ff' if dark else '#1759a4',
                  'assistant': '#8cdda8' if dark else '#23743d',
                  'debug': '#f1c575' if dark else '#8a5907',
                  'local': '#e59eac' if dark else '#a52e49'}
        roles = {'user': tr('用户发送的消息'), 'assistant': 'AI',
                 'debug': tr('调试结果'), 'local': tr('本地处理')}
        blocks = []
        self._message_contents = {}
        for index, record in enumerate(self.conversations):
            kind = record.get('kind', 'request')
            entries = []
            if kind == 'request':
                request = {'instructions': record.get('instructions', ''), 'content': record.get('request', {})}
                message = record.get('user_message', '')
                body = (message + '\n\n' if message else '') + json.dumps(request, ensure_ascii=False, indent=2)
                entries.append(('user', body))
                if record.get('response'):
                    entries.append(('assistant', record['response']))
                elif record.get('state') == 'sending':
                    entries.append(('assistant', tr('正在等待 AI 回复…')))
                elif record.get('state') == 'cancelled':
                    entries.append(('local', tr('已取消')))
                if record.get('local'):
                    entries.append(('local', json.dumps(record['local'], ensure_ascii=False, indent=2)))
            elif kind == 'context':
                entries.append(('user', record.get('content', '')))
            else:
                entries.append(('debug' if kind == 'debug' else 'local', json.dumps(record, ensure_ascii=False, indent=2)))
            for role, content in entries:
                key = '%s-%s' % (index, role)
                content = str(content)
                self._message_contents[key] = (roles[role], content)
                ai_message, details = display_reply(content) if role == 'assistant' else ('', content)
                presentation = '\n\n'.join(filter(None, (ai_message, details)))
                preview, truncated = self.message_preview(presentation)
                expanded = key in self._expanded_messages
                shown = presentation if expanded else preview
                rendered = render_body(shown, ai_message, details)
                control = (' <a href="toggle:%s" style="color:%s">%s</a>' %
                           (key, colors[role], escape(tr('收起') if expanded else tr('展开')))) if truncated else ''
                # Escape all source and model output; only our fold controls are links.
                try:
                    stamp = datetime.fromisoformat(record.get('time', '').replace('Z', '+00:00')).astimezone().strftime('%Y-%m-%d %H:%M:%S')
                except (ValueError, TypeError):
                    stamp = str(record.get('time', ''))
                check = '☑' if key in self._selected_messages else '☐'
                blocks.append('<table width="100%%"><tr><td style="color:%s"><b>%s</b></td>'
                              '<td align="right">%s &nbsp; <a href="select:%s" style="text-decoration:none;font-size:18px;color:%s">%s</a></td></tr></table>'
                              '%s%s<hr>' %
                              (colors[role], escape(roles[role]), escape(stamp), key, colors[role], check,
                               rendered, control))
        self.conversation.setHtml(''.join(blocks))
        scrollbar.setValue(scrollbar.maximum() if follow else position)

    def message_preview(self, content):
        document = QTextDocument()
        document.setDefaultFont(self.conversation.font())
        document.setPlainText(content)
        document.setTextWidth(max(80, self.conversation.viewport().width() - 32))
        document.documentLayout().documentSize()
        block, count, cutoff = document.begin(), 0, 0
        while block.isValid():
            layout = block.layout()
            for index in range(layout.lineCount()):
                if count == 5:
                    # QTextDocument indexes UTF-16 units, including emoji surrogate pairs.
                    preview = content.encode('utf-16-le')[:cutoff * 2].decode('utf-16-le', errors='ignore')
                    return preview.rstrip()[:-1] + '…', True
                line = layout.lineAt(index)
                cutoff = block.position() + line.textStart() + line.textLength()
                count += 1
            block = block.next()
        return content, False

    def toggle_message(self, url):
        if url.scheme() not in ('toggle', 'select'):
            return
        position = self.conversation.verticalScrollBar().value()
        key = url.path()
        selected = self._selected_messages if url.scheme() == 'select' else self._expanded_messages
        if key in selected:
            selected.remove(key)
        else:
            selected.add(key)
        self.render_conversation()
        self.conversation.verticalScrollBar().setValue(position)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, 'conversation'):
            QTimer.singleShot(0, self.render_conversation)

    def copy_selected_information(self):
        messages = ['%s:\n%s' % self._message_contents[key] for key in self._message_contents
                    if key in self._selected_messages]
        if messages:
            QApplication.clipboard().setText('\n\n'.join(messages))
            self.status.setText(tr('信息已复制，可粘贴给其他 AI。'))
            return
        selected = self.conversation.textCursor().selectedText()
        if selected:
            QApplication.clipboard().setText(selected.replace('\u2029', '\n').replace('\u2028', '\n'))
            self.status.setText(tr('信息已复制，可粘贴给其他 AI。'))
        else:
            self.status.setText(tr('请先选择要复制的对话内容。'))

    def selected_history(self):
        return self.selected_context()[0]

    def selected_local_information(self):
        return self.selected_context()[1]

    def selected_context(self):
        from ..service.script_information import selected_context
        return selected_context(self.conversations, self._selected_messages if self.send_selected.isChecked() else None)

    def copy_information(self, *_, all_records=False):
        records = self.conversations if all_records else self.conversations[-1:]
        QApplication.clipboard().setText(portable_markdown(records))
        self.status.setText(tr('信息已复制，可粘贴给其他 AI。'))

    def export_information(self):
        path, _ = QFileDialog.getSaveFileName(self, tr('导出信息历史'), Path(self.dict_path).stem + '-information.md', 'Markdown (*.md)')
        if path:
            try:
                Path(path).write_text(portable_markdown(self.conversations), encoding='utf-8')
                self.status.setText(tr('信息历史已导出。'))
            except OSError:
                self.status.setText(tr('导出失败，请检查保存路径。'))

    def import_conversation(self):
        if self.loader:
            return
        path, _ = QFileDialog.getOpenFileName(self, tr('导入对话'), '', 'Text / Markdown (*.txt *.md)')
        if not path:
            return
        try:
            with open(path, encoding='utf-8-sig') as stream:
                content = stream.read(1000001)
            if len(content) > 1000000:
                raise ValueError(tr('对话文件过大。'))
            if not content.strip():
                raise ValueError(tr('对话文件为空。'))
            self.add_information({'kind': 'context', 'content': content, 'filename': Path(path).name})
            self.tabs.setCurrentIndex(3)
        except (OSError, ValueError, UnicodeError) as error:
            self.status.setText(str(error))

    def ready(self, result):
        if self._closed or self.token != profile_token():
            return
        warning = ''
        if 'history_sessions' in result:
            sessions = [s for s in result['history_sessions'] if s['id'] != self.session_id and s['id'] not in self.imported_sessions]
            if not sessions:
                self.status.setText(tr('没有可导入的旧会话。'))
                return
            labels = ['%s · %s · %s' % (s['time'] or tr('旧版记录'), s['count'], s['id'][:8]) for s in sessions]
            selected, accepted = QInputDialog.getItem(self, tr('导入之前的会话'), tr('选择此词典的会话'), labels, 0, False)
            if accepted and not self._closed and self.token == profile_token():
                selected_id = sessions[labels.index(selected)]['id']
                self._pending_import = selected_id
                QTimer.singleShot(0, self._start_pending_import)
            return
        if 'history_records' in result:
            imported = result.get('import_session')
            count = 0
            for value in result['history_records']:
                if value.get('dictionary_id') != dictionary_identity(self.dict_path):
                    continue
                value = deepcopy(value)
                if imported:
                    value['imported_from'] = {'session_id': imported, 'record_id': value['id']}
                    value['id'], value['session_id'] = uuid.uuid4().hex, self.session_id
                    value.pop('storage_saved', None)
                self.add_information(value)
                count += 1
            if imported:
                self.imported_sessions.add(imported)
            self.tabs.setCurrentIndex(3)
            self.status.setText(tr('已导入 %s 条信息；之后可携带当前会话全部对话。') % count)
            return
        record = result.get('record')
        if record:
            warning = self.add_information(record)
            self.samples_view.setPlainText(json.dumps(record.get('request', {}), ensure_ascii=False, indent=2))
        debug = result.get('debug_record')
        if debug:
            for secret in self._secret_values:
                debug = redact(debug, secret)
            self.last_debug = debug
            warning = self.add_information(debug) or warning
            self.tabs.setCurrentIndex(3)
        if result.get('error'):
            self.status.setText('\n'.join(filter(None, (result['error'],
                               tr('保留上次有效脚本，未应用本次回复。') if self.result else '', warning))))
            self.tabs.setCurrentIndex(3)
            return
        if result.get('chat_only'):
            self.status.setText('\n'.join(filter(None, (tr('AI 已回复，未修改当前脚本。'), warning))))
            self.tabs.setCurrentIndex(3)
            return
        if result.get('source'):
            self.result = result
            self._result_saved = False
            if self.last_debug and self.last_debug.get('source_sha256') != sha256(result['source'].encode()).hexdigest():
                self.last_debug = None
            self.preview.setPlainText(json.dumps(result['preview'], ensure_ascii=False, indent=2))
            prompt = result.get('prompt') or build_prompt(result['samples'], None, result.get('javascript'))
            self.samples_view.setPlainText(json.dumps(json.loads(prompt), ensure_ascii=False, indent=2))
            self.source_view.setPlainText(result['source'])
            unavailable = result['rules']['unavailable']
            if result.get('format') == 'python':
                message = tr('Python 语法和结构检查通过，尚未执行。可查看源码后点击调试。')
                self.tabs.setCurrentIndex(2)
            else:
                message = tr('规则已通过三个样本的提取检查。未找到的字段：%s') % ('、'.join(unavailable) or tr('无'))
            self.save_button.setEnabled(True)
            self.debug_button.setEnabled(True)
        else:
            message = ''
        if debug:
            message += '\n' + (tr('调试通过：本次导出方法和媒体引用检查完成。') if debug.get('passed') else tr('调试发现问题，请查看信息历史中的词条、字段和错误详情。'))
        self.status.setText('\n'.join(filter(None, (message, warning))))

    def failed(self, error=''):
        if not self._closed:
            self.add_information({'kind': 'local', 'error_type': str(error), 'error': tr('操作失败，当前脚本未覆盖。')})
            self.status.setText(tr('操作失败，当前脚本未覆盖。'))

    def finished_loading(self):
        self.loader = None
        if not self._closed:
            self.generate.setEnabled(True)
            self.edit_script_button.setEnabled(True)
            self.send_message.setEnabled(True)
            self.debug_button.setEnabled(bool(self.result))
            self.save_button.setEnabled(bool(self.result) and not self._result_saved)
            self.restore_button.setEnabled(True)
            QTimer.singleShot(0, self._start_pending_import)
            for widget in [self.profile_combo, self.command, self.return_json, *self.words, *self.attachments.values()]:
                widget.setEnabled(True)

    def show_output_help(self):
        content = tr('勾选（默认）：AI 返回解释和完整规则，由插件生成 Python，适合常规提取。\n\n'
                     '不勾选：AI 返回解释和完整 Python，适合复杂处理，需查看代码并调试。两种模式都可以只回复消息，不修改脚本。')
        content += '\n\n' + tr('注意 Token 消耗：携带历史、源码和调试信息会增加用量。')
        dialog = Dialog(self, tr('输出方式说明'))
        dialog.resize(560, 240)
        layout = QVBoxLayout(dialog)
        viewer = QTextBrowser()
        viewer.setPlainText(content)
        layout.addWidget(viewer)
        dialog.exec()

    def edit_script(self):
        if self.loader or self.token != profile_token():
            return
        if self.result and not self._result_saved:
            self.status.setText(tr('请先保存当前脚本，再打开编辑。'))
            return
        path = next((Path(item) for item in self.script_paths if Path(item).is_file()), None)
        if path is None:
            self.status.setText(tr('请先生成并保存脚本，再打开编辑。'))
            return
        try:
            import tokenize
            with tokenize.open(path) as stream:
                source = stream.read()
            from ..utils.script_editor import open_script
            open_script(path)
            self._editing_path, self._editing_source = path, source
            self.status.setText(tr('已用文本编辑器打开脚本。保存文件后，下次发送或调试会重新读取。'))
        except (OSError, ValueError):
            self.status.setText(tr('无法打开文本编辑器，请检查脚本文件和本机编辑器。'))

    def sync_edited_script(self):
        if self._editing_path is None:
            return True
        try:
            import tokenize
            with tokenize.open(self._editing_path) as stream:
                source = stream.read(500001)
            if source == self._editing_source:
                return True
            if self.result and not self._result_saved and self.result['source'] != self._editing_source:
                raise ValueError(tr('文件和当前预览都已修改，请先处理这两个版本，再继续发送或调试。'))
            file_source = source
            source, generated_class = parse_python(source, self.class_name)
            self.result = dict(self.result or {}, source=source, filename=self._editing_path.name,
                original={'path': str(self._editing_path), 'source': file_source}, format='python',
                class_name=generated_class, rules={'fields': [], 'unavailable': []}, preview=[])
            self._editing_source = file_source
            self._result_saved = True
            self.last_debug = None
            self.source_view.setPlainText(source)
            self.preview.clear()
            self.debug_button.setEnabled(True)
            return True
        except (OSError, ValueError, SyntaxError) as error:
            self.status.setText(tr('无法读取编辑后的脚本：') + str(error))
            return False

    def save(self):
        if self.loader or not self.result or self._result_saved or self.token != profile_token():
            return
        from .script_compare import check_scripts
        if not check_scripts(self):
            return
        directory = self.script_directory
        try:
            original = self.result.get('original')
            if original:
                path = replace_script(original['path'], self.result['source'], original['source'], directory)
            else:
                path = save_script(self.result['filename'], self.result['source'], directory)
            from ..service.script_library import publish, exclude_scripts
            exclude_scripts([Path(path).name], restore=True)
            publish(directory, self.result.get('javascript'), self.dict_path)
        except ValueError as error:
            self.status.setText(str(error))
            return
        except Exception:
            self.status.setText(tr('保存脚本失败，现有文件未覆盖。'))
            return
        self.save_button.setEnabled(False)
        self._result_saved = True
        self.script_paths = [path] + [item for item in self.script_paths if item != path]
        self.status.setText(tr('脚本已更新，旧版本已放入回收站。') if original else
                            tr('脚本已保存，默认未启用。返回词典管理勾选并保存即可使用。'))
        self.saved.emit(path)

    def open_history(self, recycled=False):
        try:
            folder = trash_directory(self.script_directory) if recycled else history_directory(self.script_directory)
            folder.mkdir(parents=True, exist_ok=True)
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder))):
                raise OSError()
        except (OSError, ValueError):
            self.status.setText(tr('无法打开信息历史目录或回收站。'))

    def restore_old_script(self):
        if self.loader or self.token != profile_token():
            return
        from .script_recycle import ScriptRecycleDialog
        try:
            dialog = ScriptRecycleDialog(self, self.script_directory)
            if dialog.exec() != QDialog.DialogCode.Accepted or not dialog.selected_path:
                return
        except (OSError, ValueError):
            self.status.setText(tr('恢复旧脚本失败。'))
            return
        filename = dialog.selected_path
        try:
            path = restore_script(filename, self.script_directory)
            from ..service.script_library import publish
            publish(self.script_directory)
            self.result = None
            self.last_debug = None
            self._result_saved = False
            self.debug_button.setEnabled(False)
            self.save_button.setEnabled(False)
            self.status.setText(tr('旧脚本已恢复，重新检测后应用。'))
            self.saved.emit(path)
        except (OSError, ValueError, SyntaxError):
            self.status.setText(tr('恢复旧脚本失败。'))

    def done(self, result):
        self._closed = True
        if self.loader:
            self.loader.stop()
        self.conversations.clear()
        super().done(result)
