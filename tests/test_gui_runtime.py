"""Optional integration checks using real Qt widgets with an isolated host.

Run with PyQt6 available and QT_QPA_PLATFORM=offscreen. No Anki collection or
external dictionary files are opened or modified.
"""

import importlib.util
import os
import sys
import time
import types
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import test_modularization as support


@unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'PyQt6 is not installed')
class GuiRuntimeTests(unittest.TestCase):
    def test_about_content_is_localized_and_uses_current_project_links(self):
        sys.modules.pop(support.PACKAGE + '.constants', None)
        constants = self.load('constants')
        i18n = self.load('i18n')
        with i18n.use_language('en'):
            english = constants.Template.about_html()
        with i18n.use_language('zh-CN'):
            chinese = constants.Template.about_html()
        self.assertIn('MDX', english)
        self.assertIn('使用 AI', chinese)
        for text in (english, chinese):
            self.assertIn('FastWordQuery', text)
            self.assertIn('GPL-3.0-or-later', text)
            self.assertIn(constants.Endpoint.repository, text)
            self.assertIn(constants.Endpoint.feedback_issue, text)
            self.assertIn('mailto:jiangrz0213@gmail.com', text)
            self.assertNotIn('hi.fanjialiang@gmail.com', text)
        module = self.load('gui.common')
        with patch.object(module, 'Template', constants.Template), patch.object(module.QMessageBox, 'about') as show:
            module.show_about_dialog(None)
        self.assertIsNone(show.call_args.args[0])
        self.assertIn('FastCard Maker', show.call_args.args[2])

    def test_deleted_task_menu_actions_disconnect_from_hub_and_job(self):
        from PyQt6 import sip
        module = self.load('gui.task_progress')
        hub = module.progress_hub()
        class Report(self.qt.QObject):
            changed = self.qt.pyqtSignal()
        report = Report()
        report.token = self.load('utils.media').profile_token()
        report.cancelled, report.done = False, False
        report.completed, report.total = 2, 5
        baseline = [hub.receivers(signal) for signal in (hub.started, hub.completed, hub.reset)]
        wrappers = []
        for _ in range(20):
            parent = self.qt.QMenu()
            action = module.TaskMenuAction(parent)
            action.bind(report)
            self.assertIn('2 / 5', action.text())
            wrappers.append(action)  # Keep Python wrappers alive after C++ deletion.
            sip.delete(parent)
        self.assertTrue(all(sip.isdeleted(action) for action in wrappers))
        self.assertEqual([hub.receivers(signal) for signal in (hub.started, hub.completed, hub.reset)], baseline)
        self.assertEqual(report.receivers(report.changed), 0)
        hub.started.emit(report)
        hub.completed.emit(report)
        report.changed.emit()
        hub.reset.emit()
        self.assertFalse(self.errors, self.errors)

    def test_script_compare_defaults_to_backup_and_headers_choose_exclusively(self):
        module = self.load('gui.script_compare')
        dialog = module.ScriptCompareDialog(None, {'a.py': {'source': 'x=1'}},
                                            {'a.py': {'source': 'x=2'}, 'b.py': {'source': 'x=3'}})
        self.widgets.append(dialog)
        self.assertTrue(all(checks[1].isChecked() for _, checks, _ in dialog.rows))
        dialog.heads[0].click()
        self.assertTrue(all(checks[0].isChecked() and not checks[1].isChecked() for _, checks, _ in dialog.rows))
        dialog.rows[0][1][1].click()
        self.assertEqual(dialog.heads[0].checkState(), self.qt.Qt.CheckState.PartiallyChecked)
        self.assertEqual(dialog.table.columnCount(), 3)
        captured = []
        def inspect(viewer):
            editor = viewer.findChild(self.qt.QPlainTextEdit)
            captured.append((editor.isReadOnly(), editor.toPlainText()))
            return 0
        with patch.object(module.Dialog, 'exec', inspect):
            dialog.view('a.py', dialog.backup)
        self.assertEqual(captured, [(True, 'x=2')])

    def test_settings_return_to_initial_values_closes_without_save_prompt(self):
        self.background_host()
        sys.modules.pop(support.PACKAGE + '.gui.setting', None)
        dialog = self.load('gui.setting').SettingDialog(None)
        self.widgets.append(dialog)
        before = dialog.ai_retries.value()
        dialog.ai_retries.setValue((before + 1) % 6)
        self.assertNotEqual(dialog.widget_values(), dialog._initial_values)
        dialog.ai_retries.setValue(before)
        self.assertEqual(dialog.widget_values(), dialog._initial_values)
        with patch.object(self.load('gui.base'), 'QMessageBox') as question:
            dialog.reject()
        question.assert_not_called()

    def test_option_sync_buttons_have_explicit_local_and_media_directions(self):
        self.background_host()
        module = self.load('gui.config_sync')
        self.host.config.settings_difference.return_value = ['ai_settings']
        for action in ('overwrite', 'sync', 'cancel'):
            with patch.object(module, 'QMessageBox') as box, \
                    patch.object(self.load('service.refresh'), 'get_updater') as updater:
                dialog = box.return_value
                overwrite, sync, cancel = Mock(), Mock(), Mock()
                dialog.addButton.side_effect = [overwrite, sync, cancel]
                dialog.clickedButton.return_value = {'overwrite': overwrite, 'sync': sync, 'cancel': cancel}[action]
                self.assertTrue(module.check_settings(None))
                self.host.config.resolve_settings.assert_called_with(action)
                self.assertIn('本机 → 媒体文件夹', dialog.setInformativeText.call_args.args[0])
                if action != 'sync':
                    updater.assert_not_called()

    def test_read_config_uses_media_folder_json_filter_and_preserves_cancel(self):
        self.background_host()
        sys.modules.pop(support.PACKAGE + '.gui.setting', None)
        module = self.load('gui.setting')
        self.host.config.media_dir = str(Path(self.host.mw.pm.profileFolder()) / 'collection.media')
        self.host.config.import_settings = Mock()
        dialog = module.SettingDialog(None)
        self.widgets.append(dialog)
        with patch.object(module.QFileDialog, 'getOpenFileName', return_value=('', '')) as picker:
            dialog.read_configuration()
        self.assertEqual(picker.call_args.args[2], self.host.config.media_dir)
        self.assertIn('*.json', picker.call_args.args[3])
        self.host.config.import_settings.assert_not_called()
        self.assertFalse(dialog.configuration_loaded)
        self.assertFalse(hasattr(dialog, 'backup_button'))
        source = Path(self.host.mw.pm.profileFolder()) / 'settings.json'
        source.write_text('{"ai_send_mode":"note"}', encoding='utf-8')
        with patch.object(module.QFileDialog, 'getOpenFileName', return_value=(str(source), '')), \
                patch.object(module.QMessageBox, 'question', return_value=self.qt.QMessageBox.StandardButton.Yes), \
                patch.object(module.QMessageBox, 'information'):
            dialog.read_configuration()
        self.host.config.import_settings.assert_called_once_with({'ai_send_mode': 'note'})
        self.assertTrue(dialog.configuration_loaded)

    def test_combined_progress_has_only_background_and_cancel_actions(self):
        self.background_host()
        window = self.load('gui.query_progress').QueryProgressWindow(3, 2, 29, show_window=False)
        self.widgets.append(window)
        self.assertEqual([b.text() for b in window.findChildren(self.qt.QPushButton)], ['后台运行', '取消任务'])
        window.cancel_button.click()
        self.assertTrue(window.dictionary.abort())
        self.assertTrue(window.ai.abort())
        self.assertFalse(window.cancel_button.isEnabled())

    def test_settings_categories_and_always_visible_style_types(self):
        self.background_host()
        sys.modules.pop(support.PACKAGE + '.gui.setting', None)
        dialog = self.load('gui.setting').SettingDialog(None)
        self.widgets.append(dialog)
        self.assertEqual([dialog.settings_tabs.tabText(i) for i in range(3)], ['AI 设置', '词典设置', '通用设置'])
        self.assertFalse(dialog.css_panel.isAncestorOf(dialog.style_types))
        self.assertTrue(dialog.css_panel.isHidden())
        dialog.css_toggle.setChecked(True)
        dialog.css_toggle.setChecked(False)
        self.assertFalse(dialog.style_types.isHidden())
        dialog.ai_connect_timeout.setValue(17)
        dialog.ai_retries.setValue(0)
        dialog.ai_rate.setValue(50)
        dialog.save()
        settings = self.load('service.ai_config')
        self.assertEqual(settings.transport_settings()['connect_timeout'], 17)
        self.assertEqual(settings.transport_settings()['retries'], 0)
        self.assertEqual(settings.ai_send_rate(), 50)

    def test_options_remembers_viewed_tab_without_changing_query_default(self):
        dialog = self.dialog()
        dialog.addTab({'name': 'Second', 'fields': deepcopy(self.maps)})
        dialog.tab_widget.setCurrentIndex(1)
        dialog.save()
        saved = self.controller.save_config.call_args.args[1]
        self.assertEqual(saved['viewed'], 1)
        self.assertEqual(saved['def'], 0)
        self.controller.get_maps.side_effect = lambda mid: deepcopy(saved)
        reopened = self.dialog()
        self.assertEqual(reopened.tab_widget.currentIndex(), 1)
        self.assertEqual(reopened.default_tab_index, 0)

    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
        from PyQt6 import QtCore, QtGui, QtWidgets
        cls.qt = types.ModuleType('aqt.qt')
        for source in (QtCore, QtGui, QtWidgets):
            cls.qt.__dict__.update({key: value for key, value in vars(source).items()
                                    if not key.startswith('_')})
        cls.app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        sys.modules['aqt.qt'] = self.qt
        anki = types.ModuleType('anki')
        anki.__path__ = []
        anki_utils = types.ModuleType('anki.utils')
        anki_utils.is_mac = False
        sys.modules.update({'anki': anki, 'anki.utils': anki_utils})
        sys.modules[support.PACKAGE + '.context'].APP_ICON = self.qt.QIcon()
        sys.modules[support.PACKAGE + '.utils'].get_icon = lambda name: self.qt.QIcon()
        sys.modules[support.PACKAGE + '.lang']._ = lambda label: 'Config %d' if label == 'CONFIG_INDEX' else label
        del sys.modules[support.PACKAGE + '.gui.base']
        self.load = self.host.load
        self.errors = []
        self.addCleanup(patch.stopall)
        patch.object(sys, 'excepthook', lambda *args: self.errors.append(args)).start()
        self.model = {'id': 1, 'name': 'Basic', 'flds': [
            {'name': 'Word', 'ord': 0}, {'name': 'Meaning', 'ord': 1},
        ]}
        self.maps = [
            {'fld_name': 'Word', 'fld_ord': 0, 'word_checked': True},
            {'fld_name': 'Meaning', 'fld_ord': 1, 'dict_unique': 'local',
             'dict_name': 'Local', 'dict_fld_name': 'Audio', 'dict_fld_ord': 1,
             'ignore': False, 'skip_valued': True},
        ]
        self.services = {'local': [{'title': 'Local', 'unique': 'local', 'status': 'ready'}],
                         'web': [{'title': 'Online', 'unique': 'online'}]}
        self.controller = Mock()
        self.controller.get_last_model_id.return_value = 1
        self.controller.get_maps.side_effect = lambda key: {
            'list': [{'name': 'Primary', 'fields': deepcopy(self.maps)}], 'def': 0,
        }
        self.controller.load_services.side_effect = lambda **kwargs: deepcopy(self.services)
        self.controller.preview_services.side_effect = lambda: deepcopy(self.services)
        self.controller.has_cached_services.return_value = False
        self.controller.needs_background_load.return_value = True
        self.controller.get_service_fields.side_effect = lambda key: ['Definition', 'Audio'] if key in {'local', 'online'} else []
        self.controller.is_logging_enabled.return_value = False
        models = Mock()
        models.get.return_value = self.model
        models.all.return_value = [self.model]
        models.all_names_and_ids.return_value = [types.SimpleNamespace(id=1, name='Basic')]
        self.host.mw.col = types.SimpleNamespace(models=models)
        self.host.mw.app = self.app
        note_module = types.ModuleType('anki.notes')
        note_module.Note = object
        sys.modules['anki.notes'] = note_module
        sys.modules['anki'].notes = note_module
        progress = Mock()
        progress.abort.return_value = False
        sys.modules[support.PACKAGE + '.gui'].ProgressWindow = Mock(return_value=progress)
        self.host.config.thread_number = 4
        self.host.config.ignore_accents = False
        self.host.config.force_update = False
        self.host.config.ai_send_mode = 'field'
        config = self.host.config
        config.dirs = []
        config.last_folder = ''
        config.enable_logging = False
        manager = sys.modules[support.PACKAGE + '.service'].service_manager
        manager.local_custom_services = []
        manager.local_services = []
        manager.web_services = []
        self.widgets = []
        self.addCleanup(self.close_widgets)

    def close_widgets(self):
        jobs = sys.modules.get(support.PACKAGE + '.query.background')
        if jobs:
            jobs.cancel_jobs(wait=True)
        for widget in self.widgets:
            widget._is_dirty = False
            widget._snapshot_reader = None  # Cleanup does not exercise the save prompt.
            if hasattr(widget, '_stop_loading'):
                widget.done(self.qt.QDialog.DialogCode.Rejected)
            else:
                widget.close()
            widget.deleteLater()
        self.app.processEvents()
        loaders = sys.modules.get(support.PACKAGE + '.gui.service_loader')
        if loaders:
            loaders.cancel_loaders(wait=True)

    def dialog(self):
        options = self.load('gui.options')
        with patch.object(options, 'OptionsController', return_value=self.controller):
            dialog = options.OptionsDialog(None)
        self.widgets.append(dialog)
        deadline = time.monotonic() + 3
        while (not hasattr(dialog, 'tab_widget') or dialog._loading) and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.assertFalse(self.errors, self.errors)
        self.assertTrue(hasattr(dialog, 'tab_widget'), 'Service loading did not build the UI')
        return dialog

    def pump_until(self, predicate, timeout=3):
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.app.processEvents()
            time.sleep(0.001)
        self.app.processEvents()
        self.assertTrue(predicate(), 'Background operation did not finish')
        self.assertFalse(self.errors, self.errors)

    def actual_services_controller(self, factories):
        manager = types.SimpleNamespace(web_services=factories, local_services=[], revision=0)
        def create(unique):
            instance = next(factory for factory in factories if factory.__unique__ == unique)()
            instance.unique = unique
            return instance
        manager.get_service = create
        pool = self.load('service.pool').ServicePool(manager)
        package = sys.modules[support.PACKAGE + '.service']
        package.service_manager, package.service_pool = manager, pool
        self.host.config.dicts = {factory.__unique__: {'enabled': True} for factory in factories}
        self.host.config.thread_number = 16
        sys.modules['aqt.utils'].showWarning = Mock()
        del sys.modules[support.PACKAGE + '.gui.options_controller']
        module = self.load('gui.options_controller')
        controller = module.OptionsController()
        controller.get_last_model_id = self.controller.get_last_model_id
        controller.get_maps = self.controller.get_maps
        return controller, module, pool

    def background_host(self, note_fields=None):
        package = types.ModuleType(support.PACKAGE + '.query')
        package.__path__ = [str(support.SRC / 'query')]
        sys.modules[package.__name__] = package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        service_package = sys.modules[support.PACKAGE + '.service']
        service_package.QueryResult = base.QueryResult
        service_package.copy_static_file = base.copy_static_file
        sys.modules['aqt.utils'].tooltip = Mock()
        root = self.qt.QMainWindow()
        root.pm, root.app, root.reset = self.host.mw.pm, self.app, Mock()
        root.col = Mock()
        root.col.models = self.host.mw.col.models
        sys.modules['aqt'].mw = root
        self.widgets.append(root)
        root.show()
        self.model = {'id': 1, 'name': 'Test', 'flds': [{'name': name, 'ord': i}
                      for i, name in enumerate(('Word', 'Meaning', 'Example'))], 'tmpls': [{'afmt': ''}]}
        model = self.model
        class Note:
            id = 1
            def __init__(self):
                self.fields = list(note_fields or ['hello', '', ''])
            def note_type(self):
                return model
        note = Note()
        root.col.get_note.return_value = note
        module = self.load('query.background')
        return module, self.load('query.ai_runner'), base, note, root

    def query_entry(self):
        import importlib.util
        sys.modules['aqt.utils'].showText = Mock()
        name = support.PACKAGE + '.query'
        spec = importlib.util.spec_from_file_location(name, support.SRC / 'query' / '__init__.py',
                                                    submodule_search_locations=[str(support.SRC / 'query')])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module

    def test_editor_query_reads_latest_contents_only_after_save_acknowledgement(self):
        module, runner, base, note, root = self.background_host()
        entry = self.query_entry()
        root.show()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        self.host.config.get_maps = lambda model: {'list': [mappings], 'def': 0}
        class Editor:
            addMode = False
            def __init__(self):
                self.note, self.parentWindow = note, root
                self.callbacks = []
            def saveNow(self, callback, keepFocus=False):
                self.callbacks.append(callback)
        editor = root.editor = Editor()
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')) as query:
            entry.query_from_editor_fields(editor)
            self.assertIsNone(module.active_job())
            query.assert_not_called()
            note.fields[0] = 'fresh word from webview'
            editor.callbacks.pop()()
            self.pump_until(lambda: bool(editor.callbacks))
            job = module.active_job()
            self.assertEqual(query.call_args.args[2]['Word'], 'fresh word from webview')
            root.col.update_note.assert_not_called()
            note.fields[1] = 'draft typed while waiting'
            editor.callbacks.pop()()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields[1], 'draft typed while waiting')
        root.col.update_note.assert_not_called()

    def test_modern_editor_entry_and_unsaved_note_guard(self):
        module, runner, base, note, root = self.background_host()
        entry = self.query_entry()
        root.show()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        self.host.config.get_maps = lambda model: {'list': [mappings], 'def': 0}
        class Editor:
            nid, addMode = 1, False
            def __init__(self):
                self.parentWindow = root
                self.reload_note = Mock()
            def call_after_note_saved(self, callback, keepFocus=False):
                self_callback = callback
                self.qt_timer.singleShot(5, self_callback)
            def get_note_info(self, callback):
                callback(types.SimpleNamespace(id=self.nid, mid=1, fields=list(note.fields)))
        Editor.qt_timer = self.qt.QTimer
        editor = root.editor = Editor()
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='modern answer')) as query:
            entry.query_from_editor_fields(editor)
            self.pump_until(lambda: note.fields[1] == 'modern answer')
            self.pump_until(lambda: module.active_job() is None)
            editor.reload_note.assert_called_once()
            query.reset_mock()
            editor.nid, editor.addMode = None, True
            entry.query_from_editor_fields(editor)
            self.pump_until(lambda: sys.modules['aqt.utils'].tooltip.called)
            for _ in range(10):
                self.app.processEvents()
                time.sleep(0.005)
            query.assert_not_called()
            self.assertIsNone(module.active_job())
            self.assertIn('新版添加窗口', sys.modules['aqt.utils'].tooltip.call_args.args[0])

    def test_background_button_keeps_task_alive_after_options_close_and_writes_on_main(self):
        import threading
        module, runner, base, note, root = self.background_host()
        dialog = self.dialog()
        dialog.show()
        start, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        worker_threads, writer_threads = [], []
        root.col.update_note.side_effect = lambda value: writer_threads.append(threading.get_ident())
        def query(*args, **kwargs):
            worker_threads.append(threading.get_ident())
            start.set()
            release.wait(2)
            return base.QueryResult(result='answer')
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_name': 'Meaning', 'fld_ord': 1, 'dict_unique': 'ai:test',
                     'ai_prompt': 'Explain {{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model,
                                            writer=root.col.update_note, parent=dialog)
            self.pump_until(start.is_set)
            self.assertFalse(job.window.isModal())
            job.window.background_button.click()
            self.assertFalse(job.window.isVisible())
            self.assertFalse(dialog.isModal())
            self.assertIsNotNone(dialog._task_strip)
            self.assertFalse(dialog._task_strip.isVisible())
            self.assertIsNone(getattr(root, '_fwq_progress_dock', None))
            dialog.close()
            self.widgets.remove(dialog)
            dialog.deleteLater()
            self.app.sendPostedEvents(None, self.qt.QEvent.Type.DeferredDelete)
            self.assertFalse(job.done)
            release.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields[1], 'answer')
        self.assertEqual(writer_threads, [threading.get_ident()])
        self.assertNotEqual(worker_threads[0], threading.get_ident())
        self.assertIsNone(module.active_job())

    def test_background_ai_skips_manual_edit_and_preserves_unrelated_fields(self):
        import threading
        module, runner, base, note, root = self.background_host()
        start, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def query(*args, **kwargs):
            start.set()
            release.wait(2)
            return base.QueryResult(result='AI answer')
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'Explain {{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(start.is_set)
            note.fields[1] = 'manual answer'
            release.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields[1], 'manual answer')
        self.assertEqual(job.conflicts, 1)
        root.col.update_note.assert_not_called()
        start.clear()
        release.clear()
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(start.is_set)
            note.fields[2] = 'unrelated edit'
            release.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields, ['hello', 'AI answer', 'unrelated edit'])

    def test_background_dictionary_and_ai_run_together_with_independent_cancel(self):
        import threading
        module, runner, base, note, root = self.background_host()
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def query(*args, **kwargs):
            entered.set()
            release.wait(2)
            return base.QueryResult(result='AI answer')
        dictionary = Mock()
        dictionary.active.return_value = base.QueryResult(result='dictionary answer')
        sys.modules[support.PACKAGE + '.service'].service_pool.get.return_value = dictionary
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'local', 'dict_fld_ord': 0, 'ignore': False},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(entered.is_set)
            job.window.run_in_background()
            job.window.ai.cancel()
            self.pump_until(lambda: note.fields[1] == 'dictionary answer')
            release.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields, ['hello', 'dictionary answer', ''])
        self.assertTrue(job.ai.was_cancelled)
        self.assertFalse(job.dictionary.cancelled)

    def test_background_merge_is_atomic_and_duplicate_start_does_not_submit(self):
        import threading
        module, runner, base, note, root = self.background_host()
        self.host.config.ai_profiles = [dict(self.load('service.ai_config').new_profile('deepseek'),
                                            id='test', send_mode='note')]
        self.host.config.ai_send_mode = 'note'
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        def query(*args, **kwargs):
            entered.set()
            release.wait(2)
            return {'Meaning': base.QueryResult(result='meaning'), 'Example': base.QueryResult(result='example')}
        mappings = [{'fld_name': 'Word', 'word_checked': True}] + [
            {'fld_ord': index, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}
            for index in (1, 2)]
        with patch.object(runner, 'query_ai_many', side_effect=query) as requests:
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(entered.is_set)
            self.assertIs(module.start_query_session([note], mappings=mappings, model=self.model), job)
            note.fields[2] = 'manual edit'
            release.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(requests.call_count, 1)
        self.assertEqual(note.fields, ['hello', '', 'manual edit'])
        self.assertEqual(job.conflicts, 2)
        root.col.update_note.assert_not_called()
        note.fields = ['hello', '', '']
        with patch.object(runner, 'query_ai_many', return_value={
                'Meaning': base.QueryResult(result='meaning'), 'Example': base.QueryResult(result='example')}) as requests:
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(lambda: job.done)
        requests.assert_called_once()
        self.assertEqual(note.fields, ['hello', 'meaning', 'example'])
        root.col.update_note.assert_called_once()

    def test_shared_css_settings_are_collapsed_and_never_modify_card_styles(self):
        _, _, _, _, root = self.background_host()
        root.col.models.all.return_value = [dict(self.model), dict(self.model, id=2, name='Concepts')]
        sys.modules.pop(support.PACKAGE + '.gui.setting', None)
        dialog = self.load('gui.setting').SettingDialog(None)
        self.widgets.append(dialog)
        self.assertTrue(all(dialog.style_types.item(i).checkState() == self.qt.Qt.CheckState.Checked
                            for i in range(dialog.style_types.count())))
        self.assertFalse(dialog.ai_css_enabled.isChecked())
        self.assertFalse(dialog.css_toggle.isChecked())
        self.assertTrue(dialog.css_panel.isHidden())
        dialog.ai_css_enabled.setChecked(True)
        dialog.style_types.item(0).setCheckState(self.qt.Qt.CheckState.Unchecked)
        dialog.style_css.setPlainText('.fwq-ai .fwq-table { color: blue; }')
        dialog.ai_send_mode.setCurrentIndex(dialog.ai_send_mode.findData('note'))
        dialog.save()
        root.col.models.update_dict.assert_not_called()
        root.col.models.save.assert_not_called()
        saved = self.host.config.update.call_args.args[0]
        self.assertEqual(saved['ai_css'], '.fwq-ai .fwq-table { color: blue; }')
        self.assertEqual(saved['ai_styles'], {'1': {'enabled': False}, '2': {'enabled': True}})
        self.assertEqual(saved['ai_send_mode'], 'note')
        dialog.ai_css_enabled.setChecked(False)
        dialog.save()
        root.col.models.update_dict.assert_not_called()

    def test_css_is_deferred_until_real_successful_write_and_uses_global_snapshot(self):
        module, runner, base, note, root = self.background_host()
        fmt = self.load('utils.ai_format')
        self.host.config.ai_css_enabled = True
        self.host.config.ai_styles = {'1': {'enabled': True}}
        self.host.config.ai_css = fmt.DEFAULT_CSS
        model = dict(self.model, css='.card { color: red; }')
        root.col.models.get.side_effect = lambda mid: deepcopy(model)
        root.col.models.update_dict.side_effect = lambda updated: model.update(updated)
        maps = [{'fld_name': 'Word', 'word_checked': True},
                {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')):
            job = module.start_query_session([note], mappings=maps, model=self.model)
            root.col.models.update_dict.assert_not_called()
            self.pump_until(lambda: job.done)
        self.assertIn(fmt.START, model['css'])
        self.assertEqual(root.col.models.update_dict.call_count, 1)
        self.host.config.ai_css = fmt.DEFAULT_CSS.replace('line-height: 1.6', 'line-height: 1.9')
        maps[1]['skip_valued'] = True
        with patch.object(runner, 'query_ai') as request:
            job = module.start_query_session([note], mappings=maps, model=self.model)
            self.pump_until(lambda: job.done)
            request.assert_not_called()
        self.assertEqual(root.col.models.update_dict.call_count, 1)
        maps[1]['skip_valued'] = False
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='')):
            job = module.start_query_session([note], mappings=maps, model=self.model)
            self.pump_until(lambda: job.done)
        self.assertEqual(root.col.models.update_dict.call_count, 1)
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')):
            job = module.start_query_session([note], mappings=maps, model=self.model)
            self.pump_until(lambda: job.done)
        self.assertEqual(root.col.models.update_dict.call_count, 1)
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='new answer')):
            job = module.start_query_session([note], mappings=maps, model=self.model)
            self.pump_until(lambda: job.done)
        self.assertEqual(root.col.models.update_dict.call_count, 2)
        self.assertIn('line-height: 1.9', model['css'])
        root.col.update_note.side_effect = RuntimeError('save failed')
        self.host.config.ai_css = fmt.DEFAULT_CSS
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='not committed')):
            job = module.start_query_session([note], mappings=maps, model=self.model)
            job.background()
            self.pump_until(lambda: job.done)
        self.assertEqual(root.col.models.update_dict.call_count, 2)
        self.assertEqual(note.fields[1], 'new answer')

    def test_ai_concept_cards_preserve_passages_and_write_combined_fields(self):
        topic = '机会成本：为什么选择一项行动会放弃其他收益？\n请结合时间分配解释。'
        module, runner, base, note, root = self.background_host([topic, '', ''])
        self.model['flds'] = [{'name': name, 'ord': i}
                              for i, name in enumerate(('Topic', 'Explanation', 'SelfTest'))]
        self.host.config.ai_profiles = [dict(self.load('service.ai_config').new_profile('deepseek'), id='test')]
        self.host.config.ai_send_mode = 'note'
        mappings = [{'fld_name': 'Topic', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '解释 {{Topic}}', 'ignore': False},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': '针对 {{Topic}} 出题并给出答案', 'ignore': False}]
        with patch.object(runner, 'query_ai_many', return_value={
                'Explanation': base.QueryResult(result='解释和类比'),
                'SelfTest': base.QueryResult(result='问题和答案')}) as requests:
            job = module.start_query_session([note], mappings=mappings, model=self.model,
                                            writer=root.col.update_note)
            self.pump_until(lambda: job.done)
        requests.assert_called_once()
        self.assertEqual(requests.call_args.args[2]['Topic'], topic)
        self.assertEqual(set(requests.call_args.args[1]), {'Explanation', 'SelfTest'})
        self.assertEqual(note.fields, [topic, '解释和类比', '问题和答案'])
        root.col.update_note.assert_called_once()

    def test_background_dictionary_skips_changed_source_and_editor_drafts(self):
        import threading
        module, runner, base, note, root = self.background_host()
        for change_source in (True, False):
            entered, release = threading.Event(), threading.Event()
            self.addCleanup(release.set)
            def active(*args, **kwargs):
                entered.set()
                release.wait(2)
                return base.QueryResult(result='dictionary answer')
            dictionary = Mock()
            dictionary.active.side_effect = active
            sys.modules[support.PACKAGE + '.service'].service_pool.get.return_value = dictionary
            mappings = [{'fld_name': 'Word', 'word_checked': True},
                        {'fld_ord': 1, 'dict_unique': 'local', 'dict_fld_ord': 0, 'ignore': False}]
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(entered.is_set)
            editor_window = self.qt.QWidget()
            self.widgets.append(editor_window)
            editor_window.show()
            draft = types.SimpleNamespace(id=1, fields=list(note.fields))
            draft.fields[0 if change_source else 1] = 'manual edit'
            editor_window.editor = types.SimpleNamespace(note=draft)
            release.set()
            self.pump_until(lambda: job.done)
            self.assertEqual(note.fields, ['hello', '', ''])
            self.assertEqual(job.conflicts, 1)
            editor_window.editor = None
        root.col.update_note.assert_not_called()

    def test_background_save_waits_for_webview_and_skips_a_late_draft(self):
        module, runner, base, note, root = self.background_host()
        class Editor:
            currentField = 1
            def __init__(self):
                self.note = note
                self.callbacks = []
            def saveNow(self, callback, keepFocus=False):
                self.callbacks.append(callback)
        editor = root.editor = Editor()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='AI answer')):
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            job.window.run_in_background()
            self.pump_until(lambda: bool(editor.callbacks))
            root.col.update_note.assert_not_called()
            self.assertTrue(job.writing)
            self.assertFalse(job.done)
            self.assertFalse(job.window.write_status.isHidden())
            note.fields[1] = 'late webview draft'
            editor.callbacks.pop()()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields[1], 'late webview draft')
        self.assertEqual(job.conflicts, 1)
        root.col.update_note.assert_not_called()

    def test_editor_sync_timeout_or_cancellation_never_writes_a_late_result(self):
        module, runner, base, note, root = self.background_host()
        bridge = self.load('query.editor_bridge')
        for cancel in (False, True):
            callbacks = []
            class Editor:
                def __init__(self):
                    self.note = note
                def saveNow(self, callback, keepFocus=False):
                    callbacks.append(callback)
            root.editor = Editor()
            mappings = [{'fld_name': 'Word', 'word_checked': True},
                        {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
            with patch.object(bridge.EditorBarrier, 'TIMEOUT_MS', 60), \
                    patch.object(runner, 'query_ai', return_value=base.QueryResult(result='late answer')):
                job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
                job.window.run_in_background()
                self.pump_until(lambda: bool(callbacks))
                if cancel:
                    job.cancel()
                self.pump_until(lambda: job.done)
                callbacks[0]()
                self.app.processEvents()
            self.assertEqual(note.fields[1], '')
            self.assertEqual(job.ai.failed, 0 if cancel else 1)
            root.col.update_note.assert_not_called()

    def test_modern_editor_snapshot_is_checked_and_refreshed_after_save(self):
        module, runner, base, note, root = self.background_host()
        for changed in (False, True):
            note.fields[:] = ['hello', '', '']
            class Editor:
                nid = 1
                def __init__(self):
                    self.callbacks = []
                    self.reload_note = Mock()
                def call_after_note_saved(self, callback, keepFocus=False):
                    self.callbacks.append(callback)
                def get_note_info(self, callback):
                    callback(types.SimpleNamespace(id=1, mid=1,
                        fields=['hello', 'modern draft' if changed else '', '']))
            editor = root.editor = Editor()
            mappings = [{'fld_name': 'Word', 'word_checked': True},
                        {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
            with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='modern answer')):
                job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
                self.pump_until(lambda: bool(editor.callbacks))
                editor.callbacks.pop()()
                self.pump_until(lambda: job.done)
            if changed:
                self.assertEqual(job.conflicts, 1)
                self.assertEqual(note.fields[1], '')
                editor.reload_note.assert_not_called()
            else:
                self.assertEqual(note.fields[1], 'modern answer')
                editor.reload_note.assert_called_once()

    def test_background_save_notifies_anki_and_ui_refresh_failure_is_not_a_save_failure(self):
        module, runner, base, note, root = self.background_host()
        notify = Mock()
        sys.modules['aqt'].gui_hooks = types.SimpleNamespace(operation_did_execute=notify)
        changes = types.SimpleNamespace(note_text=True)
        root.col.update_note.return_value = changes
        class Editor:
            def __init__(self):
                self.note = note
            def saveNow(self, callback, keepFocus=False):
                callback()
            def setNote(self, *args, **kwargs):
                raise ValueError('display unavailable')
        root.editor = Editor()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='saved answer')):
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            job.window.run_in_background()
            self.pump_until(lambda: job.done)
        notify.assert_called_once_with(changes, job)
        self.assertEqual(note.fields[1], 'saved answer')
        self.assertEqual(job.ai.updated_fields, 1)
        self.assertEqual(job.ai.failed, 0)
        self.assertTrue(job.notices)

    def test_results_are_cached_before_end_and_saved_once_per_note(self):
        import threading
        module, runner, base, note, root = self.background_host()
        notify = Mock()
        sys.modules['aqt'].gui_hooks = types.SimpleNamespace(operation_did_execute=notify)
        root.col.update_note.return_value = types.SimpleNamespace(note_text=True)
        editor = root.editor = types.SimpleNamespace(note=note, saveNow=lambda callback, **kwargs: callback(), setNote=Mock())
        release = threading.Event()
        self.addCleanup(release.set)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'fast', 'ignore': False},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': 'slow', 'ignore': False}]
        def query(unique, prompt, *args, **kwargs):
            if prompt == 'slow':
                release.wait(5)
            return base.QueryResult(result=prompt + ' answer')
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(lambda: job.completed_ai == 1)
            self.assertEqual(note.fields, ['hello', '', ''])
            root.col.update_note.assert_not_called()
            editor.setNote.assert_not_called()
            self.pump_until(lambda: not job.cache_pending)
            self.assertTrue(job.result_cache.pending())
            release.set()
            self.pump_until(lambda: job.done)
        root.col.update_note.assert_called_once()
        editor.setNote.assert_called_once()
        notify.assert_called_once()
        self.assertEqual(note.fields, ['hello', 'fast answer', 'slow answer'])
        self.assertFalse(job.result_cache.pending())

    def test_cancelled_batch_recovers_returned_results_without_ai_request(self):
        import threading
        module, runner, base, note, root = self.background_host()
        release = threading.Event()
        self.addCleanup(release.set)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'fast', 'ignore': False},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': 'slow', 'ignore': False}]
        def query(unique, prompt, *args, **kwargs):
            if prompt == 'slow':
                release.wait(5)
            return base.QueryResult(result=prompt)
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model)
            self.pump_until(lambda: job.completed_ai == 1)
            job.cancel()
            release.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields, ['hello', '', ''])
        self.assertTrue(job.result_cache.pending())
        with patch.object(runner, 'query_ai', side_effect=AssertionError('Must not request AI again')) as query:
            recovered = module.recover_results()
            self.pump_until(lambda: recovered.done)
        query.assert_not_called()
        self.assertEqual(note.fields, ['hello', 'fast', ''])
        self.assertFalse(recovered.result_cache.pending())

    def test_batch_write_failure_rolls_back_all_fields_and_retains_cache(self):
        module, runner, base, note, root = self.background_host()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'meaning', 'ignore': False},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': 'example', 'ignore': False}]
        root.col.update_note.side_effect = RuntimeError('Database unavailable')
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='new value')):
            job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
            job.background()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields, ['hello', '', ''])
        self.assertEqual(job.ai.updated_fields, 0)
        self.assertTrue(job.result_cache.pending())
        root.col.update_note.side_effect = None
        root.col.update_note.reset_mock()
        recovered = module.recover_results()
        self.pump_until(lambda: recovered.done)
        self.assertEqual(note.fields, ['hello', 'new value', 'new value'])
        root.col.update_note.assert_called_once()
        self.assertFalse(recovered.result_cache.pending())

    def test_multiple_notes_send_one_anki_change_notification(self):
        module, runner, base, first, root = self.background_host()
        second = type(first)()
        second.id = 2
        second.fields[0] = 'second word'
        notes = {1: first, 2: second}
        root.col.get_note.side_effect = notes.__getitem__
        root.col.update_note.side_effect = [types.SimpleNamespace(note_text=True, note=False),
                                           types.SimpleNamespace(note_text=False, note=True)]
        notify = Mock()
        sys.modules['aqt'].gui_hooks = types.SimpleNamespace(operation_did_execute=notify)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')):
            job = module.start_query_session([first, second], mappings=mappings, model=self.model, writer=root.col.update_note)
            self.pump_until(lambda: job.done)
        self.assertEqual(root.col.update_note.call_count, 2)
        notify.assert_called_once()
        changes = notify.call_args.args[0]
        self.assertTrue(changes.note_text)
        self.assertTrue(changes.note)
        self.assertEqual(len(job.ai.updated_notes), 2)

    def test_slow_cache_and_cleanup_leave_ui_responsive_and_progress_can_dismiss(self):
        import threading
        from PyQt6.QtTest import QTest
        module, runner, base, first, root = self.background_host()
        dialog = self.dialog()
        dialog.show()
        second = type(first)()
        second.id = 2
        root.col.get_note.side_effect = {1: first, 2: second}.__getitem__
        writer_threads, cache_threads, cleanup_calls = [], [], []
        main_thread = threading.get_ident()
        root.col.update_note.side_effect = lambda note: writer_threads.append(threading.get_ident())
        button = self.qt.QPushButton('Still clickable')
        root.setCentralWidget(button)
        clicked = Mock()
        button.clicked.connect(clicked)
        release_cache, release_cleanup = threading.Event(), threading.Event()
        cache_entered, cleanup_entered = threading.Event(), threading.Event()
        self.addCleanup(release_cache.set)
        self.addCleanup(release_cleanup.set)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'meaning', 'ignore': False},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': 'example', 'ignore': False}]
        job = module.QueryJob([first, second], mappings=mappings, model=self.model, writer=root.col.update_note)
        original_put, original_remove = job.result_cache.put, job.result_cache.remove
        def put(*args):
            cache_threads.append(threading.get_ident())
            cache_entered.set()
            release_cache.wait(5)
            return original_put(*args)
        def remove(keys):
            cache_threads.append(threading.get_ident())
            cleanup_calls.append(len(keys))
            cleanup_entered.set()
            release_cleanup.wait(5)
            return original_remove(keys)
        job.result_cache.put, job.result_cache.remove = put, remove
        progress = self.load('gui.task_progress')
        action = progress.TaskMenuAction(root)
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')):
            job.start()
            self.pump_until(lambda: cache_entered.is_set() and job.phase == 'cache')
            strip = dialog._task_strip
            self.assertIn('等待缓存', strip.label.text())
            self.assertEqual(strip.bar.maximum(), 0)
            QTest.mouseClick(button, self.qt.Qt.MouseButton.LeftButton)
            strip.close_button.click()
            self.assertFalse(strip.isVisible())
            self.assertFalse(job.window.isVisible())
            release_cache.set()
            self.pump_until(lambda: cleanup_entered.is_set() and job.phase == 'cleanup')
            QTest.mouseClick(button, self.qt.Qt.MouseButton.LeftButton)
            self.assertEqual(clicked.call_count, 2)
            self.assertFalse(strip.isVisible())
            release_cleanup.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(cleanup_calls, [4])
        self.assertEqual(writer_threads, [main_thread, main_thread])
        self.assertTrue(all(thread != main_thread for thread in cache_threads))
        self.assertFalse(strip.isVisible())
        self.assertIn('已完成', action.text())
        action.trigger()
        report = progress.progress_hub().last
        self.widgets.append(report.window)
        self.assertEqual(set(report.timings), {'query', 'cache_wait', 'save', 'cleanup', 'refresh'})
        self.assertTrue(report.window.isVisible())

    def test_finished_progress_close_keeps_menu_result_available(self):
        module, runner, base, note, root = self.background_host()
        dialog = self.dialog()
        dialog.show()
        progress = self.load('gui.task_progress')
        action = progress.TaskMenuAction(root)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'meaning', 'ignore': False}]
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')):
            job = module.start_query_session([note], mappings=mappings, model=self.model)
            self.pump_until(lambda: job.done)
        strip = dialog._task_strip
        self.assertEqual(strip.cancel.text(), '完成任务')
        self.assertTrue(strip.cancel.isEnabled())
        self.assertEqual(strip.close_button.text(), '最小化')
        strip.cancel.click()
        self.assertFalse(strip.isVisible())
        self.assertFalse(job.cancelled)
        self.assertEqual(note.fields[1], 'answer')
        action.trigger()
        self.widgets.append(progress.progress_hub().last.window)
        self.assertTrue(progress.progress_hub().last.window.isVisible())

    def test_periodic_write_saves_complete_cards_without_clearing_late_results(self):
        import threading
        module, runner, base, first, root = self.background_host()
        second = type(first)()
        second.id, second.fields[0] = 2, 'slow card'
        root.col.get_note.side_effect = {1: first, 2: second}.__getitem__
        root.col.update_note.return_value = types.SimpleNamespace(note_text=True)
        notify = Mock()
        sys.modules['aqt'].gui_hooks = types.SimpleNamespace(operation_did_execute=notify)
        release_query, release_cleanup = threading.Event(), threading.Event()
        cleanup_entered = threading.Event()
        self.addCleanup(release_query.set)
        self.addCleanup(release_cleanup.set)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'meaning', 'ignore': False},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': 'example', 'ignore': False}]
        def query(unique, prompt, values, **kwargs):
            if values['Word'] == 'slow card' and prompt == 'example':
                release_query.wait(5)
            return base.QueryResult(result=prompt + ' answer')
        job = module.QueryJob([first, second], mappings=mappings, model=self.model, writer=root.col.update_note)
        original_remove = job.result_cache.remove
        cleanup_calls = []
        def remove(keys):
            cleanup_calls.append(len(keys))
            if len(cleanup_calls) == 1:
                cleanup_entered.set()
                release_cleanup.wait(5)
            return original_remove(keys)
        job.result_cache.remove = remove
        with patch.object(runner, 'query_ai', side_effect=query):
            job.start()
            job.background()
            self.pump_until(lambda: job.completed_ai == 3 and not job.cache_pending)
            self.assertEqual(first.fields, ['hello', '', ''])
            job.next_write_at = time.monotonic() - 1
            self.pump_until(cleanup_entered.is_set)
            self.assertEqual(first.fields, ['hello', 'meaning answer', 'example answer'])
            self.assertEqual(second.fields, ['slow card', '', ''])
            root.col.update_note.assert_called_once()
            notify.assert_called_once()
            second.fields[1] = 'manual change during the query'
            release_query.set()
            self.pump_until(lambda: job.completed_ai == 4)
            self.assertEqual(second.fields[2], '')
            release_cleanup.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(first.fields, ['hello', 'meaning answer', 'example answer'])
        self.assertEqual(second.fields, ['slow card', 'manual change during the query', 'example answer'])
        self.assertEqual(job.conflicts, 1)
        self.assertEqual(root.col.update_note.call_count, 2)
        self.assertEqual(notify.call_count, 2)
        self.assertEqual(cleanup_calls, [2, 2])
        self.assertFalse(job.result_cache.pending())

    def test_result_cache_keeps_references_without_credentials_or_media_bytes(self):
        from pathlib import Path
        module, runner, base, note, root = self.background_host()
        cache_module = self.load('query.result_cache')
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False,
                     'api_key': 'synthetic-credential-do-not-store'}]
        snapshot = module.NoteSnapshot(note, mappings)
        settings = types.SimpleNamespace(force_update=False, ignore_accents=False, cloze_str='{{c1::%s}}')
        payload = {'merged': False,
                   'tasks': [['Meaning', 1, mappings[1], {}, 'hello']],
                   'result': {'result': '[sound:cached.mp3]', 'unused': 'synthetic-credential-do-not-store'}}
        cache = cache_module.ResultCache()
        cache.put(snapshot, 'ai', payload, settings)
        records = cache_module.ResultCache().read()
        self.assertNotIn('synthetic-credential-do-not-store', str(records))
        directory = Path(root.pm.profileFolder()) / 'collection.media'
        directory.mkdir(parents=True, exist_ok=True)
        media = directory / 'cached.mp3'
        media.write_bytes(b'original-media-bytes')
        self.assertEqual(cache_module.missing_media(payload['result'], directory), [])
        self.assertEqual(cache_module.missing_media({'result': '<img src="missing.png">'}, directory), ['missing.png'])
        self.assertEqual(cache_module.missing_media({'result': '<img src="https://example.test/image.png">'}, directory), [])
        self.assertEqual(media.read_bytes(), b'original-media-bytes')
        self.assertNotIn(b'original-media-bytes', cache.path.read_bytes())

    def test_recovery_dialog_is_modeless_and_restores_from_its_button(self):
        module, runner, base, note, root = self.background_host()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        snapshot = module.NoteSnapshot(note, mappings)
        settings = types.SimpleNamespace(force_update=False, ignore_accents=False, cloze_str='{{c1::%s}}')
        cache = self.load('query.result_cache').ResultCache()
        cache.put(snapshot, 'ai', {'merged': False,
            'tasks': [['Meaning', 1, mappings[1], {}, 'hello']], 'result': {'result': 'cached answer'}}, settings)
        recovery_ui = self.load('gui.result_recovery')
        recovery_ui.show_recovery(root)
        dialog = next(widget for widget in root.findChildren(self.qt.QDialog)
                      if widget.windowTitle() == 'FastCM - 恢复未写入结果')
        self.assertFalse(dialog.isModal())
        self.assertIsNone(self.app.activeModalWidget())
        restore = next(button for button in dialog.findChildren(self.qt.QPushButton) if button.text() == '恢复结果')
        with patch.object(runner, 'query_ai', side_effect=AssertionError('No new AI request')) as query:
            restore.click()
            self.pump_until(lambda: module.active_job() is None)
        query.assert_not_called()
        self.assertEqual(note.fields[1], 'cached answer')
        self.assertFalse(cache.pending())

    def test_startup_automatically_shows_one_recovery_dialog_and_later_keeps_cache(self):
        module, runner, base, note, root = self.background_host()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        cache = self.load('query.result_cache').ResultCache()
        cache.put(module.NoteSnapshot(note, mappings), 'ai', {'merged': False,
            'tasks': [['Meaning', 1, mappings[1], {}, 'hello']], 'result': {'result': 'cached answer'}},
            types.SimpleNamespace(force_update=False, ignore_accents=False, cloze_str='{{c1::%s}}'))
        recovery_ui = self.load('gui.result_recovery')
        callbacks = []
        with patch.object(recovery_ui.QTimer, 'singleShot', side_effect=lambda delay, callback: callbacks.append(callback)):
            recovery_ui.notify_recovery()
        with patch.object(runner, 'query_ai') as query:
            callbacks.pop()()
            self.app.processEvents()
            dialog = root._fwq_recovery_dialog
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.isModal())
            self.assertIsNone(module.active_job())
            self.assertIs(recovery_ui.show_recovery(root), dialog)
            later = next(button for button in dialog.findChildren(self.qt.QPushButton) if button.text() == '稍后')
            later.click()
            self.app.sendPostedEvents(None, self.qt.QEvent.Type.DeferredDelete)
            self.assertIsNone(root._fwq_recovery_dialog)
            self.assertTrue(cache.pending())
            query.assert_not_called()
        cache.remove([key for key, _ in cache.read()])
        callbacks = []
        with patch.object(recovery_ui.QTimer, 'singleShot', side_effect=lambda delay, callback: callbacks.append(callback)):
            recovery_ui.notify_recovery()
        callbacks.pop()()
        self.assertIsNone(root._fwq_recovery_dialog)

    def test_startup_recovery_callback_ignores_a_profile_switch(self):
        module, runner, base, note, root = self.background_host()
        recovery_ui = self.load('gui.result_recovery')
        callbacks = []
        with patch.object(recovery_ui.QTimer, 'singleShot', side_effect=lambda delay, callback: callbacks.append(callback)):
            recovery_ui.notify_recovery()
        self.host.config.generation = getattr(self.host.config, 'generation', 0) + 1
        with patch.object(recovery_ui, 'show_recovery') as show:
            callbacks.pop()()
        show.assert_not_called()

    def test_recovery_checks_conflicts_and_missing_media(self):
        module, runner, base, note, root = self.background_host()
        cache = self.load('query.result_cache').ResultCache()
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        snapshot = module.NoteSnapshot(note, mappings)
        settings = types.SimpleNamespace(force_update=False, ignore_accents=False, cloze_str='{{c1::%s}}')
        task = ['Meaning', 1, mappings[1], {'Word': 'hello'}, 'hello']
        payload = {'merged': False, 'tasks': [task], 'result': {'result': 'answer'}}
        cache.put(snapshot, 'ai', payload, settings)
        note.fields[1] = 'manual change'
        recovered = module.recover_results()
        self.pump_until(lambda: recovered.done)
        self.assertEqual(note.fields[1], 'manual change')
        self.assertEqual(recovered.conflicts, 1)
        root.col.update_note.assert_not_called()
        note.fields[1] = ''
        payload['result']['result'] = '[sound:missing.mp3]'
        cache.put(snapshot, 'ai', payload, settings)
        recovered = module.recover_results()
        self.pump_until(lambda: recovered.done)
        self.assertEqual(note.fields[1], '')
        self.assertEqual(recovered.ai.failed, 1)
        self.assertTrue(cache.pending())
        root.col.update_note.assert_not_called()

    def test_background_dictionary_force_update_is_frozen_at_start(self):
        import threading
        module, runner, base, note, root = self.background_host(['hello', 'keep', ''])
        entered, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        dictionary = Mock()
        def active(*args, **kwargs):
            entered.set()
            release.wait(2)
            return base.QueryResult(result='')
        dictionary.active.side_effect = active
        sys.modules[support.PACKAGE + '.service'].service_pool.get.return_value = dictionary
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'local', 'dict_fld_ord': 0, 'ignore': False}]
        job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
        self.pump_until(entered.is_set)
        self.host.config.force_update = True
        release.set()
        self.pump_until(lambda: job.done)
        self.assertEqual(note.fields[1], 'keep')
        root.col.update_note.assert_not_called()

    def test_options_use_signals_without_nested_exec_and_keep_unsaved_edits(self):
        module, runner, base, note, root = self.background_host()
        common = self.load('gui.common')
        self.host.config.read = Mock()
        options = self.load('gui.options')
        callback = Mock()
        with patch.object(options, 'OptionsController', return_value=self.controller), \
                patch.object(options.OptionsDialog, 'exec', side_effect=AssertionError('Nested exec is forbidden')):
            dialog = common.show_options(callback=callback)
        self.widgets.append(dialog)
        self.pump_until(lambda: not dialog._loading)
        dialog.tabs[0]._options[1]['skip_check_btn'].click()
        before = deepcopy(dialog.tabs[0].data)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')):
            job = module.start_query_session([note], mappings=mappings, model=self.model, parent=dialog)
            job.window.background_button.click()
            self.assertTrue(dialog.isVisible())
            self.assertFalse(dialog.isModal())
            self.assertTrue(dialog._is_dirty)
            self.assertEqual(dialog.tabs[0].data, before)
            self.assertIn(dialog, common._open_options)
            self.pump_until(lambda: job.done)
        dialog.accept()
        self.widgets.remove(dialog)
        self.assertNotIn(dialog, common._open_options)
        callback.assert_called_once()

    def test_i18n_reads_anki_language_and_supports_custom_catalog_fallback(self):
        import tempfile
        import json
        from pathlib import Path
        locale = self.load('i18n')
        lang = types.ModuleType('anki.lang')
        lang.current_lang = 'ja_JP'
        sys.modules['anki.lang'] = lang
        self.assertEqual(locale.language(), 'ja')
        lang.current_lang = lambda: 'en_US'
        self.assertEqual(locale.language(), 'en')
        self.host.config.ui_language = 'zh-CN'
        self.assertEqual(locale.language(), 'zh-CN')
        with tempfile.TemporaryDirectory() as temp:
            Path(temp, 'fr.json').write_text(json.dumps({'_language_name': 'Français',
                '后台运行': 'Exécuter en arrière-plan'}), encoding='utf-8')
            Path(temp, 'en.json').write_text(json.dumps({'查看进度': 'View progress'}), encoding='utf-8')
            locale.catalog.cache_clear()
            with patch.object(locale, 'LOCALES', Path(temp)), locale.use_language('fr_FR'):
                self.assertEqual(self.load('translations').text('后台运行'), 'Exécuter en arrière-plan')
                self.assertEqual(self.load('translations').text('查看进度'), 'View progress')
            locale.catalog.cache_clear()

    def test_background_cancel_or_profile_switch_discards_late_results(self):
        import threading
        module, runner, base, note, root = self.background_host()
        for profile_switch in (False, True):
            entered, release = threading.Event(), threading.Event()
            self.addCleanup(release.set)
            def query(*args, **kwargs):
                entered.set()
                release.wait(2)
                return base.QueryResult(result='late answer')
            mappings = [{'fld_name': 'Word', 'word_checked': True},
                        {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
            with patch.object(runner, 'query_ai', side_effect=query):
                job = module.start_query_session([note], mappings=mappings, model=self.model, writer=root.col.update_note)
                self.pump_until(entered.is_set)
                if profile_switch:
                    self.host.config.generation = getattr(self.host.config, 'generation', 0) + 1
                else:
                    job.cancel()
                self.app.processEvents()
                release.set()
                self.pump_until(lambda: job.done)
            self.assertEqual(note.fields[1], '')
            root.col.update_note.assert_not_called()

    def test_missing_dictionary_keeps_binding_when_saving_and_reappearing(self):
        self.services['local'] = []
        dialog = self.dialog()
        row = dialog.tabs[0]._options[1]
        self.assertEqual(row['dict_combo'].currentData(), 'local')
        self.assertEqual(dialog.tabs[0].data[1]['dict_name'], 'Local')
        self.assertEqual(dialog.tabs[0].data[1]['dict_fld_name'], 'Audio')
        self.assertEqual(dialog.tabs[0].data[1]['dict_fld_ord'], 1)
        dialog.tabs[0]._options[1]['skip_check_btn'].click()
        dialog.save()
        saved = self.controller.save_config.call_args.args[1]['list'][0]['fields'][1]
        self.assertEqual(saved['dict_unique'], 'local')
        self.assertEqual(saved['dict_name'], 'Local')
        self.services['local'] = [{'title': 'Restored', 'unique': 'local', 'status': 'ready'}]
        dialog._on_services_loaded(deepcopy(self.services))
        self.assertEqual(dialog.tabs[0].data[1]['dict_unique'], 'local')
        self.assertEqual(dialog.tabs[0].data[1]['dict_name'], 'Local')
        row['dict_combo'].setCurrentIndex(row['dict_combo'].findData('online'))
        self.assertEqual(dialog.tabs[0].data[1]['dict_unique'], 'online')

    def test_minimize_keeps_queries_running_and_progress_can_restore_window(self):
        import threading
        module, runner, base, note, root = self.background_host()
        release = threading.Event()
        self.addCleanup(release.set)
        def query(*args, **kwargs):
            release.wait(3)
            return base.QueryResult(result='background answer')
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': 'Explain {{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model)
            job.window.background_button.click()
            self.assertTrue(job.window.isHidden())
            self.assertTrue(job.is_background)
            self.assertFalse(job.cancelled)
            self.assertFalse(job.done)
            job.show_progress()
            self.assertFalse(job.window.isHidden())
            release.set()
            self.pump_until(lambda: job.done)
        self.assertEqual(note.fields[1], 'background answer')

    def test_background_unblocks_clicks_and_keeps_completion_in_options_browser_and_menu(self):
        import threading
        from PyQt6.QtTest import QTest
        module, runner, base, note, root = self.background_host()
        browser = self.qt.QMainWindow()
        browser.show()
        self.widgets.append(browser)
        main_button, browser_button = self.qt.QPushButton('Main action'), self.qt.QPushButton('Browser action')
        root.setCentralWidget(main_button)
        browser.setCentralWidget(browser_button)
        clicked = Mock()
        main_button.clicked.connect(clicked)
        browser_button.clicked.connect(clicked)
        dialog = self.dialog()
        dialog.show()
        progress = self.load('gui.task_progress')
        action = progress.TaskMenuAction(browser)
        browser.menuBar().addMenu('FastCM').addAction(action)
        release = threading.Event()
        self.addCleanup(release.set)
        def query(*args, **kwargs):
            release.wait(3)
            return base.QueryResult(result='answer')
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', side_effect=query):
            job = module.start_query_session([note], mappings=mappings, model=self.model, parent=browser)
            QTest.mouseClick(job.window.background_button, self.qt.Qt.MouseButton.LeftButton)
            self.app.processEvents()
            self.assertIsNone(self.app.activeModalWidget())
            self.assertFalse(dialog.isModal())
            self.assertFalse(dialog._task_strip.isVisible())
            self.assertIsNone(getattr(browser, '_fwq_progress_dock', None))
            self.assertIsNone(getattr(root, '_fwq_progress_dock', None))
            QTest.mouseClick(main_button, self.qt.Qt.MouseButton.LeftButton)
            QTest.mouseClick(browser_button, self.qt.Qt.MouseButton.LeftButton)
            self.assertEqual(clicked.call_count, 2)
            self.assertIn('运行中', action.text())
            job.show_progress()
            QTest.keyClick(job.window, self.qt.Qt.Key.Key_Escape)
            self.app.processEvents()
            self.assertFalse(job.window.isVisible())
            self.assertFalse(job.done)
            self.assertIsNone(self.app.activeModalWidget())
            release.set()
            self.pump_until(lambda: job.done)
        self.assertFalse(dialog._task_strip.isVisible())
        self.assertIn('已完成', dialog._task_strip.label.text())
        self.assertIn('已完成', action.text())
        self.assertEqual(dialog._task_strip.details.text(), '查看结果')
        self.assertIsInstance(dialog._task_strip.job, progress.ProgressReport)
        self.assertFalse(hasattr(progress.progress_hub().last, 'snapshots'))
        action.trigger()
        report = progress.progress_hub().last
        self.widgets.append(report.window)
        self.assertFalse(report.window.isModal())
        reopened = self.dialog()
        reopened.show()
        self.assertIsNotNone(reopened._task_strip)
        self.assertFalse(reopened._task_strip.isVisible())
        self.assertIn('已完成', reopened._task_strip.label.text())
        self.assertFalse(self.errors, self.errors)

    def test_profile_close_clears_progress_report_and_browser_menu_status(self):
        module, runner, base, note, root = self.background_host()
        progress = self.load('gui.task_progress')
        action = progress.TaskMenuAction(root)
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='answer')):
            job = module.start_query_session([note], mappings=mappings, model=self.model)
            self.pump_until(lambda: job.done)
        self.assertIsNotNone(progress.progress_hub().last)
        progress.progress_hub().clear()
        self.assertIsNone(progress.progress_hub().last)
        self.assertFalse(action.isEnabled())
        self.assertIsNone(getattr(root, '_fwq_progress_dock', None))

    def test_manual_source_selection_survives_disappearing_before_and_after_save(self):
        for save_first in (False, True):
            dialog = self.dialog()
            tab = dialog.tabs[0]
            row = tab._options[1]
            row['dict_combo'].setCurrentIndex(row['dict_combo'].findData('online'))
            selected = deepcopy(tab.data[1])
            if save_first:
                dialog.save()
            services = deepcopy(self.services)
            services['web'] = []
            dialog._on_services_loaded(services)
            row['skip_check_btn'].click()
            dialog.save()
            saved = self.controller.save_config.call_args.args[1]['list'][0]['fields'][1]
            for key in ('dict_unique', 'dict_name', 'dict_fld_name', 'dict_fld_ord'):
                self.assertEqual(saved[key], selected[key], (save_first, key))
            self.assertNotIn('⚠', saved['dict_name'])

    def test_invalid_dictionary_field_is_visible_and_preserved_until_manual_selection(self):
        dialog = self.dialog()
        tab = dialog.tabs[0]
        row = tab._options[1]
        row['selected_mapping'].update(dict_fld_name='Removed', dict_fld_ord=99)
        with self.qt.QSignalBlocker(row['field_combo']):
            tab.fill_field_combo_options(row['field_combo'], 'Local', 'local', 'Removed', 99)
        self.assertIn('⚠', row['field_combo'].currentText())
        self.assertEqual(tab.data[1]['dict_fld_ord'], 99)
        row['field_combo'].setCurrentIndex(0)
        self.assertEqual(tab.data[1]['dict_fld_ord'], 0)
        self.assertNotIn('⚠', tab.data[1]['dict_fld_name'])

    def test_localized_catalogs_placeholders_and_adaptive_toolbar(self):
        import json
        import re
        locale = self.load('i18n')
        source = json.loads((support.SRC / 'locales/zh-CN.json').read_text(encoding='utf-8'))
        for code in ('en', 'ja'):
            translated = locale.catalog(code)
            for key, value in source.items():
                if key == '_language_name':
                    continue
                self.assertIn(key, translated, (code, key))
                self.assertEqual(re.findall(r'%[sd]|\{\d+\}', value),
                                 re.findall(r'%[sd]|\{\d+\}', translated[key]), (code, key))
        for code, label in [('zh_CN', '后台运行'), ('ja_JP', 'バックグラウンドで実行'), ('en_US', 'Run in background')]:
            with locale.use_language(code):
                self.assertEqual(self.load('translations').text('后台运行'), label)
                dialog = self.dialog()
                dialog.resize(720, 480)
                dialog.show()
                self.app.processEvents()
                flow = self.load('gui.flow_layout').FlowLayout
                for layout in dialog.findChildren(flow):
                    rect = layout.geometry()
                    for index in range(layout.count()):
                        item = layout.itemAt(index)
                        self.assertLessEqual(item.geometry().right(), rect.right() + 1)
                        self.assertLessEqual(item.geometry().bottom(), rect.bottom() + 1)
                        self.assertGreaterEqual(item.geometry().width(), item.sizeHint().width())
                ai = self.load('gui.ai_settings').AISettingsDialog(None)
                self.widgets.append(ai)
                self.assertEqual(ai.send_mode.currentData(), 'field')
        with locale.use_language('fr-FR'):
            self.assertEqual(self.load('translations').text('后台运行'), 'Run in background')

    def test_static_web_metadata_avoids_constructors_and_warm_reload(self):
        base = self.load('service.base')
        constructed = Mock()
        @base.register(['Static'])
        class Static(base.WebService):
            def __init__(self):
                constructed()
                raise RuntimeError('Must not instantiate a static source')
            @base.export(['Definition'])
            def definition(self):
                return ''
        factory = base.service_wrap(Static)
        factory.__unique__, factory.__title__ = 'Static', 'Static'
        controller, _, _ = self.actual_services_controller([factory])
        self.assertEqual(controller.preview_services()['web'][0]['fields'], ('Definition',))
        controller.dict_services = controller.load_services()
        constructed.assert_not_called()
        self.assertEqual(controller.get_service_fields('Static'), ('Definition',))
        self.controller = controller
        dialog = self.dialog()
        self.assertIsNone(dialog.loader_thread)
        self.assertFalse(dialog._loading)

    def test_twenty_slow_sources_allow_immediate_close_without_late_results(self):
        import threading
        base = self.load('service.base')
        started, release = threading.Event(), threading.Event()
        self.addCleanup(release.set)
        @base.register(['Slow'])
        class Slow(base.WebService):
            def __init__(self):
                started.set()
                release.wait(2)
                super().__init__()
            @property
            def support(self):
                return True
            @base.export(['Definition'])
            def definition(self):
                return ''
        factories = []
        for index in range(20):
            factory = base.service_wrap(Slow)
            factory.__unique__, factory.__title__ = 'Slow%d' % index, 'Slow %d' % index
            factories.append(factory)
        controller, module, _ = self.actual_services_controller(factories)
        options = self.load('gui.options')
        with patch.object(options, 'OptionsController', return_value=controller):
            dialog = options.OptionsDialog(None)
        self.widgets.append(dialog)
        dialog.show()
        self.pump_until(started.is_set)
        self.assertTrue(hasattr(dialog, 'tab_widget'))
        self.assertTrue(dialog._loading)
        before = deepcopy(dialog.dict_services)
        loader = dialog.loader_thread
        start = time.perf_counter()
        dialog.close()
        self.assertLess(time.perf_counter() - start, 0.1)
        self.assertTrue(dialog._closed)
        self.assertTrue(loader.isRunning())
        self.assertIsNone(dialog.loader_thread)
        self.widgets.remove(dialog)
        dialog.deleteLater()
        self.app.sendPostedEvents(None, self.qt.QEvent.Type.DeferredDelete)
        release.set()
        loaders = self.load('gui.service_loader')
        self.pump_until(lambda: not loaders._ACTIVE_LOADERS)
        self.assertEqual(controller.dict_services, before)
        self.assertFalse(module._CACHE, 'Cancelled work must not populate the cache')

    def test_background_metadata_refresh_preserves_edits_and_restores_fields(self):
        dialog = self.dialog()
        row = dialog.tabs[0]._options[1]
        row['skip_check_btn'].click()
        before = deepcopy(dialog.tabs[0].data)
        dialog._on_services_loaded(deepcopy(self.services))
        self.assertEqual(dialog.tabs[0].data, before)
        self.assertTrue(dialog._is_dirty)
        self.assertEqual(row['field_combo'].count(), 2)
        self.controller.get_service_fields.side_effect = lambda key: ['Audio', 'Definition']
        dialog._on_services_loaded(deepcopy(self.services))
        self.assertEqual(row['field_combo'].currentText(), 'Audio')
        self.assertEqual(row['field_combo'].currentData(), 0)
        self.assertTrue(dialog._is_dirty)

    def test_registry_update_continues_after_window_closes_and_publishes_on_main(self):
        import threading
        module = self.load('service.refresh')
        dialog = self.dialog()
        updater = dialog._updater
        self.addCleanup(lambda: updater.cancel(wait=True))
        started, release = threading.Event(), threading.Event()
        threads, writes = [], []
        main = threading.get_ident()
        prepared = types.SimpleNamespace(enabled_scripts={'NewScript'})
        def scan(settings, cancelled):
            threads.append(threading.get_ident())
            started.set()
            release.wait(2)
            return prepared
        updater.manager.adopt.side_effect = lambda value: writes.append(threading.get_ident())
        self.host.config.update.side_effect = lambda data: writes.append(threading.get_ident())
        with patch.object(module, 'scan_registry', side_effect=scan):
            start = time.perf_counter()
            updater.request(folder_sync=True)
            self.assertLess(time.perf_counter() - start, 0.1)
            self.pump_until(started.is_set)
            dialog.close()
            self.assertTrue(updater.busy)
            release.set()
            self.pump_until(lambda: not updater.busy)
        updater.manager.adopt.assert_called_once_with(prepared)
        updater.pool.clean.assert_called_once()
        self.assertNotEqual(threads[0], main)
        self.assertEqual(writes, [main, main])
        self.assertFalse(self.host.config.update.call_args.args[0]['dicts']['NewScript']['enabled'])

    def test_registry_coalesces_latest_snapshot_and_rejects_old_profile(self):
        import threading
        module = self.load('service.refresh')
        updater = module.RegistryUpdater(Mock(), Mock())
        self.addCleanup(lambda: updater.cancel(wait=True))
        started, release = threading.Event(), threading.Event()
        snapshots = []
        def scan(settings, cancelled):
            snapshots.append(settings)
            if len(snapshots) == 1:
                started.set()
                release.wait(2)
            return types.SimpleNamespace(enabled_scripts=set())
        with patch.object(module, 'scan_registry', side_effect=scan):
            updater.request(folder_sync=True)
            self.pump_until(started.is_set)
            self.host.config.dirs = ['latest']
            updater.request()
            self.host.config.dirs.append('later edit')
            release.set()
            self.pump_until(lambda: not updater.busy)
        self.assertEqual(len(snapshots), 2)
        self.assertEqual(snapshots[1].dirs, ['latest'])
        self.assertTrue(snapshots[1].folder_sync)
        updater.manager.adopt.assert_called_once()
        updater.manager.reset_mock()
        started.clear()
        release.clear()
        def stale_scan(settings, cancelled):
            started.set()
            release.wait(2)
            return types.SimpleNamespace(enabled_scripts=set())
        with patch.object(module, 'scan_registry', side_effect=stale_scan):
            updater.request()
            self.pump_until(started.is_set)
            self.host.config.generation = 1
            release.set()
            self.pump_until(lambda: not updater.busy)
        updater.manager.adopt.assert_not_called()

    def test_registry_failure_retains_sources_and_shows_retry_message(self):
        module = self.load('service.refresh')
        dialog = self.dialog()
        before = deepcopy(dialog.tabs[0].data)
        with patch.object(module, 'scan_registry', side_effect=RuntimeError('broken script')):
            dialog.refresh_sources()
            self.pump_until(lambda: not dialog._updater.busy)
        self.assertFalse(dialog.loading_label.isHidden())
        self.assertIn('重新检测词典', dialog.loading_label.text())
        self.assertEqual(dialog.tabs[0].data, before)
        dialog._updater.manager.adopt.assert_not_called()

    def test_window_build_mapping_and_save(self):
        dialog = self.dialog()
        self.assertEqual(dialog.tab_widget.count(), 1)
        self.assertFalse(dialog._is_dirty)

        data = dialog.tabs[0].data
        self.assertEqual(data[1]['dict_unique'], 'local')
        self.assertEqual(data[1]['dict_fld_ord'], 1)
        dialog.tabs[0]._options[1]['skip_check_btn'].click()
        self.assertTrue(dialog._is_dirty)
        dialog.save()
        saved = self.controller.save_config.call_args.args[1]
        self.assertEqual(saved['list'][0]['name'], 'Primary')
        self.assertFalse(saved['list'][0]['fields'][1]['skip_valued'])
        self.assertFalse(dialog._is_dirty)

    def test_ai_parameters_follow_preset_but_are_user_editable(self):
        dialog = self.load('gui.ai_settings').AISettingsDialog(None)
        self.widgets.append(dialog)
        import json
        self.assertEqual(json.loads(dialog.parameters.toPlainText())['temperature'], 1)
        dialog.provider.setCurrentIndex(dialog.provider.findData('deepseek'))
        dialog.address.setText('https://example.test/chat/completions')
        dialog.address_edited()
        self.assertEqual(json.loads(dialog.parameters.toPlainText())['thinking'], {'type': 'disabled'})
        dialog.parameters.setPlainText('{"top_p":0.4}')
        dialog.model.setText('any-model')
        dialog.address.setText('https://example.test/responses')
        dialog.address_edited()
        self.assertEqual(json.loads(dialog.parameters.toPlainText()), {'top_p': .4})
        self.assertFalse(hasattr(dialog, 'temperature'))
        self.assertFalse(hasattr(dialog, 'reasoning'))

    def test_add_remove_rename_and_default_tab(self):
        dialog = self.dialog()
        dialog.addTab({'name': 'Second', 'fields': deepcopy(self.maps)})
        self.assertEqual(dialog.tab_widget.count(), 2)
        bar = dialog.tab_widget.tabBar()
        bar._editor.setText('Renamed')
        bar.handleEditingFinished()
        self.assertEqual(dialog.tab_widget.tabText(1), 'Renamed')
        dialog.default_tab_index = 1
        dialog.removeTab(0)
        self.assertEqual(dialog.default_tab_index, 0)
        self.assertEqual(dialog.tab_widget.tabText(0), 'Renamed')
        dialog.removeTab(0)
        self.assertEqual(dialog.tab_widget.count(), 1)
        self.assertFalse(self.errors, self.errors)

    def test_status_refresh_preserves_field_mapping_and_dirty_flag(self):
        dialog = self.dialog()
        before = dialog.tabs[0].data
        dialog.check_dict_status('local', 'ready')
        self.assertEqual(dialog.tabs[0].data, before)
        self.assertFalse(dialog._is_dirty)
        self.assertFalse(self.errors, self.errors)

    def test_mapping_source_and_ignore_controls(self):
        dialog = self.dialog()
        rows = dialog.tabs[0]._options
        rows[1]['word_check_btn'].click()
        self.assertFalse(rows[1]['dict_combo'].isEnabled())
        self.assertFalse(rows[1]['ignore_check_btn'].isEnabled())
        self.assertTrue(rows[0]['ignore_check_btn'].isEnabled())
        rows[0]['ignore_check_btn'].click()
        self.assertTrue(rows[0]['dict_combo'].isEnabled())
        self.assertFalse(self.errors, self.errors)

    def test_folder_and_dictionary_windows_build_and_save(self):
        folders = self.load('gui.foldermanager').FoldersManageDialog(None)
        self.widgets.append(folders)
        self.assertEqual(folders.tree.topLevelItemCount(), 0)
        folders.chk_export_media.click()
        folders.save()
        self.assertFalse(self.host.config.update.call_args.args[0]['export_media'])
        manager = sys.modules[support.PACKAGE + '.service'].service_manager
        manager.web_services = [types.SimpleNamespace(
            __title__='Online', __unique__='online', __path__='',
        )]
        dictionaries = self.load('gui.dictmanager').DictManageDialog(None)
        self.widgets.append(dictionaries)
        self.assertEqual(len(dictionaries._options), 1)
        dictionaries._options[0]['check_btn'].click()
        dictionaries.save()
        self.assertTrue(self.host.config.update.call_args.args[0]['dicts']['online']['enabled'])
        self.assertFalse(self.errors, self.errors)

    def test_options_only_configures_and_does_not_override_global_sending_mode(self):
        dialog = self.dialog()
        self.assertFalse(hasattr(dialog, 'batch_query_btn'))
        self.assertFalse(hasattr(dialog, 'config_ai'))
        self.assertFalse(hasattr(dialog, 'run_batch_query'))
        labels = [button.text() for button in dialog.findChildren(self.qt.QPushButton)]
        self.assertNotIn('全局运行', labels)
        self.assertNotIn('恢复未写入结果', labels)
        self.assertIn('插件设置', labels)
        self.host.config.update.reset_mock()
        dialog.save()
        for call in self.host.config.update.call_args_list:
            self.assertNotIn('ai_send_mode', call.args[0])

    def test_global_ai_sending_mode_is_configured_in_plugin_settings(self):
        self.background_host()
        if hasattr(self.host.config, 'ai_send_mode'):
            del self.host.config.ai_send_mode
        sys.modules.pop(support.PACKAGE + '.gui.setting', None)
        dialog = self.load('gui.setting').SettingDialog(None)
        self.widgets.append(dialog)
        self.assertEqual(dialog.ai_send_mode.currentData(), 'note')
        dialog.ai_send_mode.setCurrentIndex(dialog.ai_send_mode.findData('field'))
        dialog.save()
        self.assertEqual(self.host.config.update.call_args.args[0]['ai_send_mode'], 'field')

    def test_type_query_defaults_to_browser_selected_types_and_requires_explicit_query(self):
        module, _, _, note, root = self.background_host()
        other_model = dict(self.model, id=2, name='Concepts')
        other = type(note)()
        other.id = 2
        other.note_type = lambda: other_model
        root.col.models.all.return_value = [self.model, other_model]
        root.col.models.get.side_effect = lambda mid: self.model if mid == 1 else other_model
        root.col.get_note.side_effect = {1: note, 2: other}.__getitem__
        maps = [{'fld_name': 'Word', 'word_checked': True},
                {'fld_ord': 1, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        self.host.config.get_maps = lambda mid: {'list': [{'name': 'First', 'fields': maps},
                                                       {'name': 'Second', 'fields': deepcopy(maps)}], 'def': 1}
        def ids(sql, *args):
            if 'distinct mid' in sql:
                return list(set(args))
            mid, cursor = args
            return [mid] if cursor == 0 else []
        root.col.db.list.side_effect = ids
        entry = self.load('gui.type_query')
        browser = types.SimpleNamespace(mw=root, selectedNotes=lambda: [1, 2, 1])
        self.assertEqual(entry.selected_model_ids(browser), {1, 2})
        self.assertEqual(entry.selected_model_ids(None), set())
        browser.selectedNotes = lambda: []
        self.assertEqual(entry.selected_model_ids(browser), set())
        empty = entry.TypeQueryDialog(root)
        self.widgets.append(empty)
        self.assertTrue(all(row[1].checkState(0) == self.qt.Qt.CheckState.Unchecked for row in empty.rows))
        with patch.object(module, 'start_query_session') as launch:
            empty.run()
            launch.assert_not_called()
            dialog = entry.TypeQueryDialog(root, {1, 2})
            self.widgets.append(dialog)
            dialog.show()
            self.app.processEvents()
            launch.assert_not_called()
            self.assertTrue(all(row[2].currentData() == 1 for row in dialog.rows))
            dialog.run()
            self.pump_until(lambda: launch.called)
            notes = launch.call_args.args[0]
            self.assertEqual({n.id for n in notes}, {1, 2})
            self.assertTrue(all(n._query_mappings == maps for n in notes))
            self.assertFalse(dialog.isVisible())

    def test_type_query_cancel_during_preparation_does_not_start_task(self):
        module, _, _, _, root = self.background_host()
        self.host.config.get_maps = lambda mid: {'list': [{'fields': self.maps}], 'def': 0}
        root.col.models.all.return_value = [self.model]
        entry = self.load('gui.type_query')
        dialog = entry.TypeQueryDialog(root, {1})
        self.widgets.append(dialog)
        dialog.show()
        with patch.object(module, 'start_query_session') as launch:
            dialog.run()
            self.assertTrue(dialog.loader.isActive())
            dialog.reject()
            self.app.processEvents()
            self.assertFalse(dialog.loader.isActive())
            launch.assert_not_called()

    def test_main_and_browser_menu_query_entries_use_the_same_dialog(self):
        _, _, _, _, root = self.background_host()
        self.query_entry()
        hooks = {}
        hook_module = types.ModuleType('anki.hooks')
        hook_module.addHook = lambda name, callback: hooks.setdefault(name, []).append(callback)
        hook_module.remHook = Mock()
        hook_module.wrap = lambda function, callback, position: function
        sys.modules['anki.hooks'] = hook_module
        addcards = types.ModuleType('aqt.addcards')
        addcards.AddCards = type('AddCards', (), {'setupButtons': Mock()})
        sys.modules['aqt.addcards'] = addcards
        utils = sys.modules['aqt.utils']
        utils.downArrow, utils.shortcut = Mock(), lambda value: value
        context = sys.modules[support.PACKAGE + '.context']
        context.Config = Mock()
        gui = sys.modules[support.PACKAGE + '.gui']
        gui.show_options, gui.show_about_dialog = Mock(), Mock()
        common = self.load('common')
        root.menuBar().addMenu('帮助')
        entry = self.load('gui.type_query')
        with patch.object(entry, 'show_type_query') as show:
            common.config_menu()
            self.assertEqual([a.text() for a in root.menuBar().actions()], ['帮助', 'FastCM'])
            menu = root.menuBar().actions()[-1].menu()
            self.assertEqual([a.text() for a in menu.actions()], ['全类型查询', 'OPTIONS', '后台任务：暂无任务', 'ABOUT'])
            menu.actions()[0].trigger()
            show.assert_called_once_with()
            menu.actions()[-1].trigger()
            gui.show_about_dialog.assert_called_once_with(root)
            gui.show_about_dialog.reset_mock()
            show.reset_mock()
            browser = self.qt.QMainWindow()
            self.widgets.append(browser)
            browser.mw = root
            browser.form = types.SimpleNamespace(menubar=browser.menuBar())
            browser.selectedNotes = lambda: []
            self.host.config.get_maps = lambda mid: {'list': [{'name': 'First', 'fields': self.maps}], 'def': 0}
            common.browser_menu()
            hooks['browser.setupMenus'][0](browser)
            browser_menu = browser.menuBar().actions()[0].menu()
            self.assertEqual([a.text() for a in browser_menu.actions()][:2], ['QUERY_SELECTED', '全类型查询'])
            browser_menu.actions()[1].trigger()
            show.assert_called_once_with(browser)
            next(action for action in browser_menu.actions() if action.text() == 'ABOUT').trigger()
            gui.show_about_dialog.assert_called_once_with(browser)

    def test_rebranded_cache_can_recover_new_and_legacy_databases_together(self):
        module, _, _, note, _ = self.background_host()
        from types import SimpleNamespace
        cache = self.load('query.result_cache').ResultCache()
        snapshot = module.NoteSnapshot(note, self.maps)
        settings = SimpleNamespace(force_update=False, ignore_accents=False, cloze_str='{{c1::%s}}')
        payload = {'merged': False, 'tasks': [['Meaning', 1, self.maps[1], {}, 'hello']],
                   'result': {'result': 'answer'}}
        old_key = cache.put(snapshot, 'ai', payload, settings)
        cache.path.rename(cache.legacy_path)
        self.assertTrue(cache.pending())
        self.assertEqual(cache.read()[0][0], old_key)
        new_key = cache.put(snapshot, 'ai', payload, settings)
        self.assertEqual(cache.path.name, 'fastcm-pending.sqlite')
        self.assertEqual({key for key, _ in cache.read()}, {old_key, new_key})
        cache.remove([old_key])
        self.assertEqual([key for key, _ in cache.read()], [new_key])
        cache.remove([new_key])
        self.assertFalse(cache.pending())

    def test_global_mode_and_profile_skill_are_frozen_for_a_running_job(self):
        module, runner, base, note, root = self.background_host()
        profile = dict(self.load('service.ai_config').new_profile('deepseek'), id='test', skill='First AI skill')
        self.host.config.ai_profiles = [profile]
        self.host.config.ai_send_mode = 'note'
        mappings = [{'fld_name': 'Word', 'word_checked': True}] + [
            {'fld_ord': i, 'fld_name': name, 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}
            for i, name in enumerate(('Meaning', 'Example'), 1)]
        received = []
        def merged(unique, prompts, values, **kwargs):
            received.append(kwargs['connection'].profile['skill'])
            return {name: base.QueryResult(result='merged ' + name) for name in prompts}
        with patch.object(runner, 'query_ai_many', side_effect=merged):
            job = module.start_query_session([note], mappings=mappings, model=self.model)
            profile['skill'] = 'Edited AI skill'
            self.host.config.ai_send_mode = 'field'
            self.pump_until(lambda: job.done)
        self.assertEqual(job.ai.total_requests, 1)
        self.assertEqual(received, ['First AI skill'])
        def separate(*args, **kwargs):
            received.append(kwargs['connection'].profile['skill'])
            return base.QueryResult(result='separate')
        with patch.object(runner, 'query_ai', side_effect=separate):
            job = module.start_query_session([note], mappings=mappings, model=self.model)
            self.pump_until(lambda: job.done)
        self.assertEqual(job.ai.total_requests, 2)
        self.assertEqual(received[1:], ['Edited AI skill', 'Edited AI skill'])

    def test_ai_profile_list_keeps_independent_skills_and_parameters(self):
        dialog = self.load('gui.ai_settings').AISettingsDialog(None)
        self.widgets.append(dialog)
        for name, params in [('First', '{"top_p":0.3}'), ('Second', '{"top_p":0.7}')]:
            dialog.name.setText(name)
            dialog.address.setText('https://example.test/chat/completions')
            dialog.model.setText('test-model')
            dialog.skill.setPlainText(name + ' instructions')
            dialog.parameters.setPlainText(params)
            if name == 'First':
                dialog.add_profile()
        dialog.list.setCurrentRow(0)
        self.assertEqual(dialog.skill.toPlainText(), 'First instructions')
        self.assertIn('0.3', dialog.parameters.toPlainText())
        dialog.accept()
        profiles = self.load('service.ai_config').profiles()
        self.assertEqual([item['skill'] for item in profiles], ['First instructions', 'Second instructions'])
        self.assertEqual([item['parameters']['top_p'] for item in profiles], [.3, .7])

    def test_ai_settings_rejects_invalid_json_before_saving(self):
        module = self.load('gui.ai_settings')
        dialog = module.AISettingsDialog(None)
        self.widgets.append(dialog)
        dialog.model.setText('any-model')
        dialog.address.setText('https://example.test/responses')
        dialog.parameters.setPlainText('{invalid json')
        with patch.object(module.QMessageBox, 'warning') as warning:
            dialog.accept()
            warning.assert_called_once()
        self.assertTrue(dialog.details.isChecked())

    def test_ai_prompt_switch_and_save(self):
        self.services['ai'] = [{'title': 'Custom AI', 'unique': 'ai:test'}]
        dialog = self.dialog()
        row = dialog.tabs[0]._options[1]
        combo = row['dict_combo']
        combo.setCurrentIndex(combo.findData('ai:test'))
        row['prompt_edit'].setPlainText('Explain {{Word}}')
        self.assertEqual(dialog.tabs[0].data[1]['dict_fld_ord'], 0)
        self.assertTrue(row['prompt_edit'].isEnabled())
        combo.setCurrentIndex(combo.findData('online'))
        combo.setCurrentIndex(combo.findData('ai:test'))
        self.assertEqual(row['prompt_edit'].toPlainText(), 'Explain {{Word}}')
        dialog.check_dict_status('local', 'ready')
        self.assertEqual(dialog.tabs[0].data[1]['ai_prompt'], 'Explain {{Word}}')
        row['ignore_check_btn'].click()
        self.assertFalse(row['prompt_edit'].isEnabled())
        dialog.save()
        saved = self.controller.save_config.call_args.args[1]['list'][0]['fields'][1]
        self.assertEqual(saved['dict_unique'], 'ai:test')
        self.assertEqual(saved['ai_prompt'], 'Explain {{Word}}')
        self.assertFalse(self.errors, self.errors)

    def test_prompt_accepts_chinese_ime_composition_and_commit(self):
        prompt = self.load('gui.ai_mapping').PromptCombo()
        self.widgets.append(prompt)
        prompt.show()
        prompt.showPopup()
        self.app.processEvents()
        self.assertTrue(prompt.editor.testAttribute(self.qt.Qt.WidgetAttribute.WA_InputMethodEnabled))
        self.assertEqual(prompt.editor.inputMethodHints(), self.qt.Qt.InputMethodHint.ImhNone)
        self.assertNotEqual(prompt.popup.windowType(), self.qt.Qt.WindowType.Popup)
        preedit = self.qt.QInputMethodEvent('zhongwen', [])
        self.app.sendEvent(prompt.editor, preedit)
        self.assertTrue(prompt.composing)
        escape = self.qt.QKeyEvent(self.qt.QEvent.Type.KeyPress, self.qt.Qt.Key.Key_Escape,
                                  self.qt.Qt.KeyboardModifier.NoModifier)
        self.assertFalse(prompt.eventFilter(prompt.editor, escape))
        self.assertTrue(prompt.popup.isVisible())
        commit = self.qt.QInputMethodEvent()
        commit.setCommitString('请解释 {{单词}} 的中文含义')
        self.app.sendEvent(prompt.editor, commit)
        self.assertFalse(prompt.composing)
        self.assertEqual(prompt.toPlainText(), '请解释 {{单词}} 的中文含义')
        self.assertIn('中文含义', prompt.itemText(0))
        self.app.sendEvent(prompt.editor, escape)
        self.assertFalse(prompt.popup.isVisible())
        prompt.showPopup()
        self.app.processEvents()
        self.assertEqual(prompt.toPlainText(), '请解释 {{单词}} 的中文含义')
        outside = prompt.popup.geometry().bottomRight() + self.qt.QPoint(10, 10)
        click = self.qt.QMouseEvent(self.qt.QEvent.Type.MouseButtonPress,
                                   self.qt.QPointF(0, 0), self.qt.QPointF(outside),
                                   self.qt.Qt.MouseButton.LeftButton,
                                   self.qt.Qt.MouseButton.LeftButton,
                                   self.qt.Qt.KeyboardModifier.NoModifier)
        self.assertFalse(prompt.eventFilter(prompt, click))
        self.assertFalse(prompt.popup.isVisible())
        self.assertFalse(self.errors, self.errors)

    def test_skill_and_json_details_roundtrip(self):
        dialog = self.load('gui.ai_settings').AISettingsDialog(None)
        self.widgets.append(dialog)
        self.assertFalse(dialog.details.isChecked())
        self.assertTrue(dialog.advanced.isHidden())
        dialog.model.setText('test-model')
        dialog.address.setText('https://example.test/responses')
        dialog.skill.setPlainText('只输出答案。')
        dialog.details.click()
        dialog.parameters.setPlainText('{"temperature":1,"top_p":0.6}')
        dialog.accept()
        restored = self.load('gui.ai_settings').AISettingsDialog(None)
        self.widgets.append(restored)
        self.assertFalse(restored.details.isChecked())
        self.assertEqual(restored.skill.toPlainText(), '只输出答案。')
        self.assertIn('0.6', restored.parameters.toPlainText())
        restored.skill.setPlainText('不要保存')
        restored._snapshot_reader = None
        restored.reject()
        self.assertEqual(self.load('service.ai_config').profiles()[0]['skill'], '只输出答案。')

    def test_english_ai_window_and_original_import_are_supported(self):
        translations = self.load('translations')
        with self.load('i18n').use_language('en'):
            module = self.load('gui.ai_settings')
            dialog = module.AISettingsDialog(None)
            self.widgets.append(dialog)
            self.assertEqual(dialog.windowTitle(), 'FastCM - AI settings')
            self.assertEqual(dialog.details.text(), 'More settings (Details)')
            self.assertEqual(dialog.form.labelForField(dialog.parameters).text(), 'Custom parameters (JSON)')
            self.assertIs(module, self.load('gui.ai_ui.settings'))
            self.assertIn('Enter a custom model name', dialog.model.lineEdit().placeholderText())

    def test_ai_failures_are_aggregated_and_unknown_errors_are_safe(self):
        package = types.ModuleType(support.PACKAGE + '.query')
        package.__path__ = [str(support.SRC / 'query')]
        sys.modules[package.__name__] = package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        sys.modules[support.PACKAGE + '.service'].QueryResult = base.QueryResult
        sys.modules[support.PACKAGE + '.service'].copy_static_file = base.copy_static_file
        module = self.load('query.ai_runner')
        mappings = [{'word_checked': True}, {'fld_ord': 1, 'dict_unique': 'ai:test',
                    'ai_prompt': 'hello', 'ignore': False}]
        notes = [types.SimpleNamespace(fields=['hello', 'original']) for _ in range(4)]
        runner = module.AIQueryRunner(notes, mappings=mappings, model=self.model, flush=False)
        progress = Mock()
        progress.abort.return_value = False
        with patch.object(module, 'AIProgressWindow', return_value=progress), \
                patch.object(module, 'query_ai', side_effect=RuntimeError('secret-key-and-body')), \
                patch.object(module.QMessageBox, 'warning') as warning:
            runner.run()
        self.assertEqual(runner.failed, 4)
        warning.assert_called_once()
        report = warning.call_args.args[2]
        self.assertIn('4', report)
        self.assertNotIn('secret-key-and-body', report)
        self.assertTrue(all(note.fields[1] == 'original' for note in notes))

    def test_ai_reference_error_blocks_configuration_save(self):
        self.services['ai'] = [{'title': 'AI', 'unique': 'ai:test'}]
        dialog = self.dialog()
        row = dialog.tabs[0]._options[1]
        row['dict_combo'].setCurrentIndex(row['dict_combo'].findData('ai:test'))
        row['prompt_edit'].setPlainText('Explain {{Meaning}}')
        self.controller.save_config.reset_mock()
        with patch.object(self.qt.QMessageBox, 'warning') as warning:
            dialog.accept()
        self.controller.save_config.assert_not_called()
        warning.assert_called_once()
        self.assertIn('Meaning', warning.call_args.args[2])
        self.assertTrue(dialog._is_dirty)

    def test_ai_settings_presets_keys_and_cancel(self):
        settings = self.load('gui.ai_settings')
        credentials = self.load('service.ai_config')
        dialog = settings.AISettingsDialog(None)
        self.widgets.append(dialog)
        self.assertEqual(dialog.provider.currentData(), 'custom')
        self.assertEqual(dialog.mode.currentData(), 'responses')
        self.assertTrue(dialog.mode.isHidden())
        self.assertFalse(hasattr(dialog, 'rate'))
        dialog.key.setText('old-key')
        dialog.provider.setCurrentIndex(dialog.provider.findData('gemini'))
        self.assertEqual(dialog.mode.currentData(), 'interactions')
        self.assertEqual(dialog.list.item(0).text(), 'Gemini (缺失 API Key)')
        self.assertEqual(dialog.key.text(), '')
        dialog.provider.setCurrentIndex(dialog.provider.findData('claude'))
        self.assertEqual(dialog.mode.currentData(), 'messages')
        dialog.provider.setCurrentIndex(dialog.provider.findData('deepseek'))
        self.assertEqual(dialog.mode.currentData(), 'responses')
        dialog.model.setText('test-model')
        dialog.key.setText('only-in-memory')
        profile_id = dialog.items[0]['id']
        dialog.accept()
        self.assertEqual(credentials.session_key(profile_id), 'only-in-memory')
        saved = self.load('service.ai_store').read_settings()
        self.assertEqual(saved['keys'][profile_id], 'only-in-memory')
        self.assertNotIn('api_key', saved['profiles'][0])
        self.assertEqual(saved['requests_per_minute'], 29)
        self.host.config.ai_profiles = []
        credentials.clear_session_keys()
        cancelled = settings.AISettingsDialog(None)
        self.widgets.append(cancelled)
        self.assertEqual(cancelled.key.text(), 'only-in-memory')
        cancelled.key.setText('discard-me')
        cancelled._snapshot_reader = None  # This test checks discarded keys, not the confirmation UI.
        cancelled.reject()
        self.assertNotIn('discard-me', str(credentials._session_keys))
        self.assertEqual(credentials.session_key(profile_id), 'only-in-memory')

    def test_ai_settings_add_remove_capture(self):
        settings = self.load('gui.ai_settings')
        dialog = settings.AISettingsDialog(None)
        self.widgets.append(dialog)
        dialog.name.setText('First')
        dialog.model.setText('model-one')
        dialog.address.setText('https://example.test/v1/responses')
        dialog.key.setText('key-one')
        dialog.add_profile()
        self.assertEqual(dialog.items[0]['name'], 'First')
        dialog.name.setText('Second')
        dialog.model.setText('model-two')
        dialog.address.setText('https://example.test/v1/responses')
        dialog.list.setCurrentRow(0)
        self.assertEqual(dialog.model.text(), 'model-one')
        self.assertEqual(dialog.key.text(), 'key-one')
        dialog.remove_profile()
        self.assertEqual(dialog.name.text(), 'Second')
        dialog.accept()
        saved = self.load('service.ai_config').profiles()
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0]['name'], 'Second')

    def test_combined_send_setting_roundtrips_without_changing_legacy_default(self):
        module = self.load('gui.ai_settings')
        settings = self.load('service.ai_config')
        dialog = module.AISettingsDialog(None)
        self.widgets.append(dialog)
        self.assertEqual(dialog.send_mode.currentData(), 'field')
        dialog.name.setText('Combined')
        dialog.model.setText('test-model')
        dialog.address.setText('https://example.test/v1/responses')
        dialog.send_mode.setCurrentIndex(dialog.send_mode.findData('note'))
        self.assertIn('Markdown', dialog.send_hint.text())
        dialog.add_profile()
        self.assertEqual(dialog.send_mode.currentData(), 'field')
        dialog.name.setText('Independent')
        dialog.model.setText('test-model')
        dialog.address.setText('https://example.test/v1/responses')
        dialog.list.setCurrentRow(0)
        self.assertEqual(dialog.send_mode.currentData(), 'note')
        dialog.accept()
        self.assertEqual([item['send_mode'] for item in settings.profiles()], ['note', 'field'])
        restored = module.AISettingsDialog(None)
        self.widgets.append(restored)
        self.assertEqual(restored.send_mode.currentData(), 'note')

    def test_prompt_templates_use_selected_source_and_ai_choices_come_first(self):
        self.services['ai'] = [{'title': 'AI', 'unique': 'ai:test'}]
        dialog = self.dialog()
        tab = dialog.tabs[0]
        row = tab._options[1]
        self.assertEqual(row['dict_combo'].itemData(0), 'ai:test')
        self.assertEqual(row['dict_combo'].currentData(), 'local')
        row['dict_combo'].setCurrentIndex(row['dict_combo'].findData('ai:test'))
        editor = row['prompt_edit']
        editor.use_template(3)
        self.assertIn('{{Word}}', editor.toPlainText())
        self.assertIn('Markdown', editor.toPlainText())
        self.assertTrue(dialog._is_dirty)
        self.assertEqual(tab.data[1]['ai_prompt'], editor.toPlainText())
        tab._options[1]['word_check_btn'].click()
        first = tab._options[0]['prompt_edit']
        first.use_template(1)
        self.assertIn('{{Meaning}}', first.toPlainText())

    def test_failed_dictionary_retry_keeps_mapping_and_refreshes_status(self):
        local = self.load('service.local').LocalService
        self.services['local'][0].update(path='broken.mdx', status='failed')
        local._build_status[local.builder_key('broken.mdx')] = 'failed'
        dialog = self.dialog()
        row = dialog.tabs[0]._options[1]
        self.assertEqual(row['dict_combo'].currentData(), 'local')
        self.assertIn('初始化失败', row['dict_combo'].currentText())
        self.assertEqual(row['field_combo'].currentData(), 1)
        with patch.object(local, 'retry_build', return_value=True) as retry:
            button = next(button for button in dialog.findChildren(self.qt.QPushButton)
                          if button.text() == '重新检测词典')
            self.assertFalse(any(b.text() == '重试失败词典' for b in dialog.findChildren(self.qt.QPushButton)))
            with patch.object(dialog._updater, 'request') as rescan:
                button.click()
                rescan.assert_called_once_with()
        retry.assert_called_once_with('broken.mdx')
        dialog.check_dict_status(local.builder_key('broken.mdx'), 'ready')
        self.assertEqual(row['dict_combo'].currentData(), 'local')
        self.assertEqual(row['field_combo'].currentData(), 1)
        self.assertFalse(dialog._is_dirty)

    def test_unavailable_custom_dictionary_preserves_saved_field_mapping(self):
        self.services['ai'] = [{'title': 'AI', 'unique': 'ai:test'}]
        self.maps[1].update(dict_unique='broken', dict_name='Custom', dict_fld_name='Custom field', dict_fld_ord=4)
        dialog = self.dialog()
        row = dialog.tabs[0]._options[1]
        self.assertEqual(row['dict_combo'].currentData(), 'broken')
        self.assertEqual(row['field_combo'].currentData(), 4)
        self.assertIn('Custom field', row['field_combo'].currentText())
        self.assertIn('⚠', row['field_combo'].currentText())
        self.assertFalse(row['ignore_check_btn'].isChecked())
        self.assertEqual(dialog.tabs[0].data[1]['dict_unique'], 'broken')
        self.assertFalse(dialog._is_dirty)

    def test_dictionary_result_after_profile_switch_is_not_saved(self):
        package = types.ModuleType(support.PACKAGE + '.query')
        package.__path__ = [str(support.SRC / 'query')]
        sys.modules[package.__name__] = package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        sys.modules[support.PACKAGE + '.service'].QueryResult = base.QueryResult
        sys.modules[support.PACKAGE + '.service'].copy_static_file = base.copy_static_file
        module = self.load('query.worker')
        self.host.config.generation = 0
        manager = module.QueryWorkerManager()
        manager.writer = Mock()
        manager.total = 1
        note = types.SimpleNamespace(fields=['word', 'original'])
        self.host.config.generation = 1
        manager.handle_result(note, {1: base.QueryResult(result='stale')}, 1, [])
        self.assertEqual(note.fields[1], 'original')
        manager.writer.assert_not_called()
        self.assertEqual(manager.counter, 0)

    def test_actual_combined_session_uses_one_request_and_one_main_thread_save(self):
        import json
        import threading
        query_package = types.ModuleType(support.PACKAGE + '.query')
        query_package.__path__ = [str(support.SRC / 'query')]
        sys.modules[query_package.__name__] = query_package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        sys.modules[support.PACKAGE + '.service'].QueryResult = base.QueryResult
        sys.modules[support.PACKAGE + '.service'].copy_static_file = base.copy_static_file
        settings = self.load('service.ai_config')
        profile = settings.new_profile('custom')
        profile.update(base_url='https://example.test/v1/responses', model='test', send_mode='note')
        self.host.config.ai_send_mode = 'note'
        settings.save_profiles([profile], {profile['id']: 'test-key'})
        ai = self.load('service.ai')
        session = self.load('query.session')
        model = {'flds': [{'name': name} for name in ('Word', 'Meaning', 'Similar')]}
        note = {'Word': 'apple', 'Meaning': 'old meaning', 'Similar': 'old similar'}
        mappings = [{'fld_name': 'Word', 'word_checked': True}] + [
            {'fld_ord': index, 'dict_unique': 'ai:' + profile['id'], 'ai_prompt': 'Explain {{Word}}'}
            for index in (1, 2)]
        reply = json.dumps({'Meaning': '**fruit**', 'Similar': '| Word | Type |\n| --- | --- |\n| pear | fruit |'})
        response = Mock(status_code=200)
        response.json.return_value = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': reply}]}]}
        writes = []
        main_thread = threading.get_ident()
        with patch.object(ai, 'render_prompt', return_value='Explain apple'), \
                patch.object(ai, '_send', return_value=response) as send:
            dictionary, runner = session.run_query_session([note], mappings=mappings, model=model,
                writer=lambda current: writes.append((threading.get_ident(), dict(current))))
        send.assert_called_once()
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], main_thread)
        self.assertEqual(note['Meaning'], '<p><strong>fruit</strong></p>')
        self.assertIn('<table>', note['Similar'])
        self.assertEqual(runner.updated_fields, 2)
        self.assertEqual(runner.total_requests, 1)
        self.assertEqual(dictionary.total, 0)
        self.assertFalse(self.errors, self.errors)

    def test_single_note_ai_worker_flushes_on_main_thread(self):
        query_package = types.ModuleType(support.PACKAGE + '.query')
        query_package.__path__ = [str(support.SRC / 'query')]
        sys.modules[query_package.__name__] = query_package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        service_package = sys.modules[support.PACKAGE + '.service']
        service_package.QueryResult = base.QueryResult
        service_package.copy_static_file = base.copy_static_file
        gui_package = sys.modules[support.PACKAGE + '.gui']
        progress = Mock()
        progress.abort.return_value = False
        gui_package.ProgressWindow = Mock(return_value=progress)
        self.host.mw.app = self.app
        self.host.config.ignore_accents = False
        self.host.config.force_update = False
        self.host.config.thread_number = 2
        self.host.config.get_maps = lambda model: [
            {'word_checked': True}, {'fld_ord': 1, 'dict_fld_ord': 0,
             'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False},
        ]
        class Note:
            def __init__(self):
                self.fields = ['hello', '']
                self.flush_thread = None
            def note_type(self):
                return {'id': 1, 'flds': [{'name': 'Word'}, {'name': 'Meaning'}], 'tmpls': [{'afmt': ''}]}
            def flush(self):
                self.flush_thread = self_app.thread() == qt.QThread.currentThread()
        self_app, qt = self.app, self.qt
        note_module = types.ModuleType('anki.notes')
        note_module.Note = Note
        sys.modules['anki.notes'] = note_module
        sys.modules['anki'].notes = note_module
        worker_module = self.load('query.worker')
        common = self.load('query.common')
        manager = worker_module.QueryWorkerManager()
        self.assertTrue(manager.background_single)
        note = Note()
        manager.queue.put(note)
        with patch.object(common, 'query_ai', return_value=base.QueryResult(result='<p>AI answer</p>')):
            manager.start()
            manager.join()
        self.assertEqual(note.fields[1], '<p>AI answer</p>')
        self.assertTrue(note.flush_thread)
        failed_manager = worker_module.QueryWorkerManager()
        failed_manager.queue.put(Note())
        with patch.object(worker_module, 'query_flds', side_effect=RuntimeError('unexpected dictionary failure')):
            failed_manager.start()
            failed_manager.join()
        self.assertEqual(failed_manager.fails, 1)
        self.assertTrue(all(worker.finished for worker in failed_manager.workers))
        self.assertFalse(self.errors, self.errors)

    def test_dictionary_and_ai_overlap_with_independent_progress_and_cancel(self):
        import threading
        package = types.ModuleType(support.PACKAGE + '.query')
        package.__path__ = [str(support.SRC / 'query')]
        sys.modules[package.__name__] = package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        sys.modules[support.PACKAGE + '.service'].QueryResult = base.QueryResult
        sys.modules[support.PACKAGE + '.service'].copy_static_file = base.copy_static_file
        session = self.load('query.session')
        tasks = self.load('query.ai_runner')
        common = self.load('query.common')
        model = {'id': 1, 'flds': [{'name': name} for name in ('Word', 'Meaning', 'AI')], 'tmpls': [{'afmt': ''}]}
        class Note:
            fields = ['hello', '', '']
            def note_type(self):
                return model
        mappings = [{'word_checked': True}, {'fld_ord': 1, 'dict_unique': 'local', 'dict_fld_ord': 0},
                    {'fld_ord': 2, 'dict_unique': 'ai:test', 'ai_prompt': 'Explain {{Word}}'}]
        dictionary_started, ai_started = threading.Event(), threading.Event()
        def lookup(*args):
            dictionary_started.set()
            if not ai_started.wait(1):
                raise RuntimeError('AI did not start concurrently')
            return base.QueryResult(result='dictionary answer')
        def ai_query(*args, **kwargs):
            ai_started.set()
            if not dictionary_started.wait(1):
                raise RuntimeError('dictionary did not start concurrently')
            time.sleep(0.08)
            return base.QueryResult(result='AI answer')
        common.service_pool.get.return_value = types.SimpleNamespace(support=True, active=lookup)
        windows = []
        progress_class = session.QueryProgressWindow
        def window(*args):
            result = progress_class(*args)
            result.finish = Mock()
            windows.append(result)
            self.widgets.append(result)
            return result
        saved = []
        note = Note()
        with patch.object(session, 'QueryProgressWindow', side_effect=window), \
                patch.object(tasks, 'query_ai', side_effect=ai_query):
            dictionary, ai = session.run_query_session([note], mappings=mappings, model=model,
                writer=lambda note: saved.append(threading.get_ident()))
        self.assertEqual(note.fields, ['hello', 'dictionary answer', 'AI answer'])
        self.assertEqual(saved, [threading.get_ident()] * 2)
        self.assertTrue(windows[0].dictionary.done)
        self.assertTrue(windows[0].ai.done)
        note.fields = ['hello', '', '']
        self.qt.QTimer.singleShot(20, lambda: windows[-1].ai.cancel())
        with patch.object(session, 'QueryProgressWindow', side_effect=window), \
                patch.object(tasks, 'query_ai', side_effect=ai_query):
            dictionary, ai = session.run_query_session([note], mappings=mappings, model=model, writer=Mock())
        self.assertEqual(note.fields[1], 'dictionary answer')
        self.assertEqual(note.fields[2], '')
        self.assertFalse(dictionary.cancelled)
        self.assertTrue(ai.was_cancelled)
        self.assertFalse(self.errors, self.errors)

    def test_actual_batch_ai_writes_fields_using_original_snapshot(self):
        query_package = types.ModuleType(support.PACKAGE + '.query')
        query_package.__path__ = [str(support.SRC / 'query')]
        sys.modules[query_package.__name__] = query_package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        sys.modules[support.PACKAGE + '.service'].QueryResult = base.QueryResult
        sys.modules[support.PACKAGE + '.service'].copy_static_file = base.copy_static_file
        utils = sys.modules['aqt.utils']
        utils.showWarning = Mock()
        utils.tooltip = Mock()
        del sys.modules[support.PACKAGE + '.gui.options_controller']
        controller_module = self.load('gui.options_controller')
        tasks = self.load('query.ai_runner')
        base = self.load('service.base')
        model = {'id': 1, 'name': 'AI note', 'flds': [{'name': name} for name in ('Word', 'Meaning', 'Example')]}
        class Note:
            def __init__(self):
                self.fields = ['', 'original', '']
            def __getitem__(self, name):
                return self.fields[['Word', 'Meaning', 'Example'].index(name)]
            def __setitem__(self, name, value):
                self.fields[['Word', 'Meaning', 'Example'].index(name)] = value
            def note_type(self):
                return dict(model, tmpls=[{'afmt': ''}])
        note = Note()
        self.host.mw.col = Mock()
        self.host.mw.col.find_notes.return_value = [1]
        self.host.mw.col.get_note.return_value = note
        self.host.mw.checkpoint = Mock()
        self.host.mw.reset = Mock()
        progress = Mock()
        progress.abort.return_value = False
        mappings = [{'fld_name': 'Word', 'word_checked': True},
                    {'fld_name': 'Meaning', 'dict_unique': 'ai:test', 'dict_fld_ord': 0,
                     'ai_prompt': 'first', 'ignore': False, 'skip_valued': False},
                    {'fld_name': 'Example', 'dict_unique': 'ai:test', 'dict_fld_ord': 0,
                     'ai_prompt': 'second {{Word}}', 'ignore': False, 'skip_valued': False}]
        with patch.object(controller_module, 'ProgressWindow', return_value=progress), \
                patch.object(tasks, 'query_ai', return_value=base.QueryResult(result='<p>new</p>')) as query:
            job = controller_module.OptionsController().execute_batch_query(model, mappings)
            self.pump_until(lambda: job.done)
        self.assertEqual(note['Meaning'], '<p>new</p>')
        self.assertEqual(note['Example'], '<p>new</p>')
        self.assertEqual(query.call_count, 2)
        for call in query.call_args_list:
            self.assertEqual(call.args[2]['Meaning'], 'original')
        self.assertEqual(self.host.mw.col.update_note.call_count, 1)
        utils.showWarning.assert_not_called()
        note['Word'], note['Meaning'] = 'hello', 'original'
        dictionary_maps = [mappings[0], {'fld_name': 'Meaning', 'dict_unique': 'local',
                           'dict_fld_ord': 0, 'ignore': False, 'skip_valued': False}]
        service = Mock()
        service.active.return_value = base.QueryResult(result='dictionary answer')
        controller_module.service_pool.get.return_value = service
        self.host.mw.col.update_note.side_effect = RuntimeError('save failed')
        with patch.object(controller_module, 'ProgressWindow', return_value=progress):
            job = controller_module.OptionsController().execute_batch_query(model, dictionary_maps)
            self.pump_until(lambda: job.done)
        self.assertEqual(note['Meaning'], 'original')
        self.assertFalse(self.errors, self.errors)

    def test_independent_ai_pool_progress_and_cancellation(self):
        import threading
        query_package = types.ModuleType(support.PACKAGE + '.query')
        query_package.__path__ = [str(support.SRC / 'query')]
        sys.modules[query_package.__name__] = query_package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        sys.modules[support.PACKAGE + '.service'].QueryResult = base.QueryResult
        sys.modules[support.PACKAGE + '.service'].copy_static_file = base.copy_static_file
        module = self.load('query.ai_runner')
        self.host.config.thread_number = 1
        model = {'flds': [{'name': name} for name in ['Word'] + ['F%d' % i for i in range(6)]]}
        note = {field['name']: '' for field in model['flds']}
        note['Word'] = 'hello'
        mappings = [{'fld_name': 'Word', 'word_checked': True}] + [
            {'fld_name': 'F%d' % i, 'fld_ord': i + 1, 'dict_unique': 'ai:test',
             'ai_prompt': 'hello', 'ignore': False} for i in range(6)]
        state = {'active': 0, 'peak': 0}
        lock = threading.Lock()
        def query(*args, **kwargs):
            with lock:
                state['active'] += 1
                state['peak'] = max(state['peak'], state['active'])
            time.sleep(0.05)
            with lock:
                state['active'] -= 1
            return base.QueryResult(result='<p>answer</p>')
        progress = Mock()
        progress.abort.return_value = False
        writer_threads = []
        main_thread = threading.get_ident()
        runner = module.AIQueryRunner([note], mappings=mappings, model=model,
                                      writer=lambda note: writer_threads.append(threading.get_ident()))
        with patch.object(module, 'AIProgressWindow', return_value=progress) as window, \
                patch.object(module, 'query_ai', side_effect=query):
            runner.run()
        window.assert_called_once_with(6, 29, None)
        self.assertEqual(state['peak'], 6)
        self.assertEqual(runner.updated_fields, 6)
        self.assertEqual(writer_threads, [main_thread] * 6)
        progress.update.assert_called_with(6, 0)
        self.assertEqual(module.dictionary_notes([note], mappings=mappings), [])
        progress.abort.return_value = True
        cancelled = module.AIQueryRunner([note], mappings=mappings, model=model, writer=Mock())
        with patch.object(module, 'AIProgressWindow', return_value=progress), \
                patch.object(module, 'query_ai', side_effect=query) as requests:
            cancelled.run()
        self.assertLessEqual(requests.call_count, 6)
        cancelled.writer.assert_not_called()
        self.assertTrue(cancelled.was_cancelled)
        failed_write = module.AIQueryRunner([note], mappings=mappings, model=model,
                                           writer=Mock(side_effect=RuntimeError('save failed')))
        note['F0'] = 'original'
        task = next(task for task in failed_write.tasks if task[1] == 'F0')
        with self.assertRaisesRegex(RuntimeError, 'save failed'):
            failed_write.apply(task, base.QueryResult(result='different'))
        self.assertEqual(note['F0'], 'original')
        self.assertEqual(failed_write.updated_fields, 0)


if __name__ == '__main__':
    unittest.main()
