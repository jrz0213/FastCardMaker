"""Scheduled query boundaries, skip-busy semantics and saved stars."""
import importlib.util
import types
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch
import test_gui_runtime as gui_runtime
import test_modularization as support
import sys


@unittest.skipUnless(importlib.util.find_spec('PyQt6'), 'PyQt6 is not installed')
class AutomaticTests(unittest.TestCase):
    def test_countdown_skip_does_not_advance_scan_state_or_start_job(self):
        self.scheduler.configure()
        self.config.data['_auto_run_state']['since'] = 0
        self.root.col.db.list.return_value = [1]
        before = deepcopy(self.config.data['_auto_run_state'])
        start = Mock(return_value=Mock(done=False))
        self.scheduler._launch(start, announce=True)
        prompt = self.scheduler.countdown
        self.assertIsNotNone(prompt)
        self.assertFalse(prompt.isModal())
        self.assertEqual(self.config.data['_auto_run_state'], before)
        start.assert_not_called()
        prompt.reject()
        self.assertIsNone(self.scheduler.countdown)
        self.assertEqual(self.config.data['_auto_run_state'], before)

    def test_countdown_runs_once_after_timeout_and_rechecks_busy_state(self):
        self.scheduler.configure()
        self.config.data['_auto_run_state']['since'] = 0
        self.root.col.db.list.return_value = [1]
        start = Mock(return_value=Mock(done=False))
        self.scheduler._launch(start, announce=True)
        prompt = self.scheduler.countdown
        with patch.object(self.scheduler, '_allowed', return_value=True):
            prompt.deadline = 0
            prompt.update_countdown()
            prompt.update_countdown()
        start.assert_called_once()
        self.assertFalse(self.scheduler.job.notify_completion)
        self.scheduler.job = None
        self.scheduler._launch(start, announce=True)
        prompt = self.scheduler.countdown
        with patch.object(self.scheduler, '_allowed', return_value=False):
            prompt.launch()
        start.assert_called_once()

    def test_profile_stop_closes_countdown_without_starting(self):
        self.scheduler.configure()
        self.config.data['_auto_run_state']['since'] = 0
        self.root.col.db.list.return_value = [1]
        start = Mock()
        self.scheduler._launch(start, announce=True)
        self.scheduler.stop()
        self.assertIsNone(self.scheduler.countdown)
        start.assert_not_called()

    def setUp(self):
        gui_runtime.GuiRuntimeTests.setUpClass()
        self.host = gui_runtime.GuiRuntimeTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.background, self.runner, self.base, self.note, self.root = self.host.background_host()
        self.module = self.host.load('query.automatic')
        self.config = self.host.host.config
        self.config.auto_run = {'enabled': True, 'interval_minutes': 5, 'model_ids': [1]}
        self.config.data = {}
        self.config.cloze_str = '{{c1::%s}}'
        self.config.update.side_effect = lambda value: self.config.data.update(deepcopy(value))
        self.maps = [{'fld_name': 'Word', 'word_checked': True},
                     {'fld_name': 'Meaning', 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False},
                     {'fld_name': 'Example', 'dict_unique': 'ai:test', 'ai_prompt': '{{Word}}', 'ignore': False}]
        self.config.get_maps = lambda mid: {'list': [{'fields': self.maps}], 'auto': 0, 'def': 0}
        self.root.col.models.all.return_value = [self.host.model]
        self.scheduler = self.module.AutomaticQueries()
        self.addCleanup(self.scheduler.stop)

    def test_default_off_interval_and_new_activation_boundary(self):
        self.config.auto_run = {}
        self.scheduler.configure()
        self.assertFalse(self.scheduler.timer.isActive())
        self.config.auto_run = {'enabled': True, 'interval_minutes': 5, 'model_ids': [1]}
        with patch.object(self.module.time, 'time', return_value=100):
            self.scheduler.configure()
        self.assertTrue(self.scheduler.timer.isActive())
        self.assertEqual(self.scheduler.timer.interval(), 300000)
        self.assertEqual(self.config.data['_auto_run_state']['since'], 100000)
        self.scheduler.configure()
        self.assertEqual(self.config.data['_auto_run_state']['since'], 100000)
        self.config.auto_run['enabled'] = False
        self.scheduler.configure()
        self.assertFalse(self.scheduler.timer.isActive())
        self.config.auto_run['enabled'] = True
        with patch.object(self.module.time, 'time', return_value=200):
            self.scheduler.configure()
        self.assertEqual(self.config.data['_auto_run_state']['since'], 200000)

    def test_running_batch_skips_tick_without_search_or_queue(self):
        self.scheduler.configure()
        with patch.object(self.background, 'active_job', return_value=Mock()), patch.object(self.scheduler, '_launch') as launch:
            self.scheduler.tick()
            launch.assert_not_called()
        self.root.col.db.list.assert_not_called()

    def test_new_notes_use_starred_configuration_keep_existing_content_and_retry_bound(self):
        self.scheduler.configure()
        self.config.data['_auto_run_state']['since'] = 0
        self.note.fields = ['apple', '', 'manual example']
        self.root.col.db.list.side_effect = [[1], [], [], []]
        jobs = []
        def start(notes, **kwargs):
            job = Mock(done=False)
            job.notes, job.kwargs = notes, kwargs
            jobs.append(job)
            return job
        self.scheduler._launch(start)
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].notes[0]._query_mappings[1]['ai_prompt'], '{{Word}}')
        self.assertTrue(jobs[0].notes[0]._query_mappings[1]['skip_valued'])
        self.assertFalse(jobs[0].kwargs['query_settings'].force_update)
        jobs[0].background.assert_called_once()
        jobs[0].kwargs['on_complete'](None, None)
        self.scheduler._launch(start)
        jobs[-1].kwargs['on_complete'](None, None)
        self.scheduler._launch(start)
        jobs[-1].kwargs['on_complete'](None, None)
        self.scheduler._launch(start)
        self.assertEqual(len(jobs), 3)
        self.assertEqual(self.note.fields[2], 'manual example')
        self.assertEqual(self.config.data['_auto_run_state']['pending']['1'], {})

    def test_no_star_has_no_fallback_and_disabled_dictionary_is_skipped(self):
        self.config.get_maps = lambda mid: {'list': [{'fields': self.maps}], 'auto': -1, 'def': 0}
        self.assertIsNone(self.module.starred_mappings(self.host.model))
        self.maps[1]['dict_unique'] = 'local'
        self.config.get_maps = lambda mid: {'list': [{'fields': self.maps}], 'auto': 0, 'def': 0}
        self.assertTrue(self.module.starred_mappings(self.host.model)[1]['ignore'])

    def test_stars_exclusive_persist_and_deleting_selected_does_not_choose_another(self):
        dialog = self.host.dialog()
        dialog.addTab({'name': 'Second', 'fields': deepcopy(self.host.maps)})
        dialog.tabs[0].auto_star.click()
        self.assertEqual(dialog.auto_tab_index, 0)
        dialog.tabs[1].auto_star.click()
        dialog.tabs[1].auto_star.click()
        self.assertFalse(dialog.tabs[0].auto_star.isChecked())
        self.assertTrue(dialog.tabs[1].auto_star.isChecked())
        dialog.save()
        self.assertEqual(self.host.controller.save_config.call_args.args[1]['auto'], 1)
        dialog.removeTab(1)
        self.assertEqual(dialog.auto_tab_index, -1)
        self.assertFalse(dialog.tabs[0].auto_star.isChecked())

    def test_auto_settings_validate_star_and_save_checkboxes_and_interval(self):
        sys.modules.pop(support.PACKAGE + '.gui.setting', None)
        dialog = self.host.load('gui.setting').SettingDialog(None)
        self.host.widgets.append(dialog)
        dialog.auto_enabled.setChecked(True)
        dialog.auto_interval.setValue(7)
        dialog.auto_models.item(0).setCheckState(self.host.qt.Qt.CheckState.Checked)
        self.config.get_maps = lambda mid: {'list': [{'fields': self.maps}], 'auto': -1}
        with patch.object(self.host.qt.QMessageBox, 'warning') as warning:
            self.assertFalse(dialog.save())
            warning.assert_called_once()
        self.config.get_maps = lambda mid: {'list': [{'fields': self.maps}], 'auto': 0}
        dialog.save()
        self.assertEqual(self.config.update.call_args.args[0]['auto_run'],
                         {'enabled': True, 'interval_minutes': 7, 'model_ids': [1]})

    def test_multiple_types_keep_independent_stars_and_mappings_in_one_batch(self):
        second_model = deepcopy(self.host.model)
        second_model.update(id=2, name='Second type')
        class SecondNote:
            id = 2
            fields = ['banana', '', '']
            def note_type(self):
                return second_model
        other = SecondNote()
        self.config.auto_run['model_ids'] = [1, 2]
        self.root.col.models.all.return_value = [self.host.model, second_model]
        second_maps = deepcopy(self.maps)
        second_maps[1]['ai_prompt'] = 'Second {{Word}}'
        self.config.get_maps = lambda mid: {'list': [{'fields': self.maps},
                                                    {'fields': second_maps}],
                                           'auto': 0 if mid == 1 else 1}
        self.root.col.get_note.side_effect = lambda nid: self.note if nid == 1 else other
        self.root.col.db.list.side_effect = lambda sql, mid, cursor, limit: [mid] if cursor < mid else []
        self.scheduler.configure()
        self.config.data['_auto_run_state']['since'] = 0
        start = Mock(return_value=Mock(done=False))
        self.scheduler._launch(start)
        notes = start.call_args.args[0]
        self.assertEqual(len(notes), 2)
        self.assertEqual(notes[0]._query_mappings[1]['ai_prompt'], '{{Word}}')
        self.assertEqual(notes[1]._query_mappings[1]['ai_prompt'], 'Second {{Word}}')
        self.assertTrue(start.call_args.kwargs['start_in_background'])

    def test_unsaved_folder_detection_does_not_enable_or_publish_sources(self):
        registry = sys.modules[support.PACKAGE + '.service'].service_manager
        dialog = self.host.load('gui.dictmanager').DictManageDialog(None)
        self.host.widgets.append(dialog)
        dialog.folders._current_folders = ['unsaved-folder']
        source = types.SimpleNamespace(__title__='Discovered', __unique__='found', __path__='found.mdx')
        result = types.SimpleNamespace(local_services=[source], local_custom_services=[], web_services=[])
        refresh = self.host.load('service.refresh')
        with patch.object(refresh, 'scan_registry', return_value=result) as scan:
            dialog.detect_button.click()
            self.host.pump_until(lambda: dialog.preview_loader is None)
        self.assertEqual(scan.call_args.args[0].dirs, ['unsaved-folder'])
        self.assertFalse(dialog._options[0]['check_btn'].isChecked())
        self.config.update.assert_not_called()
        registry.adopt.assert_not_called()

    def test_unified_manager_lists_pure_mdx_and_preserves_missing_settings(self):
        registry = sys.modules[support.PACKAGE + '.service'].service_manager
        registry.local_services = [types.SimpleNamespace(__title__='Pure MDX', __unique__='pure', __path__='sample.mdx')]
        registry.local_custom_services = []
        self.config.dicts = {'missing': {'enabled': True}}
        dialog = self.host.load('gui.dictmanager').DictManageDialog(None)
        self.host.widgets.append(dialog)
        self.assertEqual(dialog.management_tabs.count(), 3)
        row = dialog._options[0]
        self.assertFalse(row['check_btn'].isChecked())
        self.assertFalse(row['edit_btn'].isHidden())
        self.assertFalse(row['edit_btn'].isEnabled())
        row['check_btn'].click()
        dialog.save()
        saved = self.config.update.call_args.args[0]
        self.assertTrue(saved['dicts']['pure']['enabled'])
        self.assertTrue(saved['dicts']['missing']['enabled'])

    def test_cached_dictionary_cannot_be_borrowed_after_disabling(self):
        enabled = {'source': True}
        service = types.SimpleNamespace(unique='source')
        manager = types.SimpleNamespace(get_service=lambda unique: service, is_enabled=lambda unique: enabled[unique])
        pool = self.host.load('service.pool').ServicePool(manager)
        pool.put(pool.get('source'))
        enabled['source'] = False
        self.assertIsNone(pool.get('source'))

