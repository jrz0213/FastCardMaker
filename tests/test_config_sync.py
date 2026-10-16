"""Real temporary files for local/media configuration and explicit resolution."""
from copy import deepcopy
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch
import test_modularization as support


class ConfigSyncTests(unittest.TestCase):
    def test_key_backup_defaults_on_can_restore_and_can_be_disabled(self):
        store = self.host.load('service.ai_store')
        store.config = self.config
        profile = {'id': 'demo', 'name': 'Demo', 'model': 'test', 'base_url': 'https://example.test/responses'}
        store.write_settings({'profiles': [profile], 'keys': {'demo': 'test-only-secret'}})
        self.assertEqual(json.loads(self.media.read_text())['credential_backup'], {'demo': 'test-only-secret'})
        store.settings_path().unlink()
        self.assertEqual(store.read_settings()['keys']['demo'], 'test-only-secret')
        self.config.update({'backup_api_keys': False, 'credential_backup': {}})
        store.write_settings({'profiles': [profile], 'keys': {'demo': 'test-only-secret'}})
        self.assertNotIn('test-only-secret', self.media.read_text())

    def test_old_fastwq_settings_are_read_but_only_new_filename_is_written(self):
        legacy = self.media.parent / '_fastwqcfg.json'
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(json.dumps({'thread_number': 7, 'dirs': ['old-local-folder']}))
        before = legacy.read_bytes()
        reopened = self.context.Config(self.host.mw)
        self.assertEqual(reopened.thread_number, 7)
        reopened.update({'thread_number': 8})
        self.assertEqual(legacy.read_bytes(), before)
        self.assertEqual(json.loads(self.media.read_text())['thread_number'], 8)
        self.assertEqual(self.context.Config(self.host.mw).thread_number, 8)

    def test_note_type_ids_from_browser_menu_are_normalized_to_json_keys(self):
        self.config.update({123: []})
        self.assertEqual(self.config.get_maps(123), [])
        self.assertIn('123', json.loads(self.media.read_text()))
        self.assertEqual(self.config.settings_difference(), [])

    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        hooks = types.ModuleType('anki.hooks')
        hooks.runHook = Mock()
        self.host.modules['anki.hooks'] = hooks
        sys.modules['anki.hooks'] = hooks
        self.host.modules[support.PACKAGE + '.constants'].VERSION = 'test'
        self.host.mw.pm.name = 'Profile'
        sys.modules.pop(support.PACKAGE + '.context', None)
        self.context = self.host.load('context')
        self.config = self.context.config
        self.media = Path(self.config.path)
        self.storage = self.host.load('utils.config_storage')

    def write_media(self, data):
        self.storage.atomic_write(self.media, data)

    def test_first_read_creates_nothing_and_save_separates_paths(self):
        self.assertFalse(self.media.exists())
        self.assertFalse(self.config.local_path.exists())
        self.config.update({'dirs': ['C:/dictionaries'], 'last_folder': 'C:/private',
                            'dicts': {'sample': {'enabled': True, 'dict_path': 'C:/dictionaries/a.mdx'}},
                            'ai_markdown': True})
        shared = json.loads(self.media.read_text())
        self.assertNotIn('dirs', shared)
        self.assertNotIn('last_folder', shared)
        self.assertNotIn('dict_path', shared['dicts']['sample'])
        self.assertTrue(shared['dicts']['sample']['enabled'])
        reopened = self.context.Config(self.host.mw)
        self.assertEqual(reopened.dirs, ['C:/dictionaries'])
        self.assertEqual(reopened.dicts['sample']['dict_path'], 'C:/dictionaries/a.mdx')

    def test_cancel_preserves_both_and_later_saves_never_overwrite_external_media(self):
        self.config.update({'ai_markdown': True, 'dirs': ['local']})
        self.write_media({'ai_markdown': False})
        self.assertIn('ai_markdown', self.config.settings_difference())
        before_media, before_local = self.media.read_bytes(), self.config.local_path.read_bytes()
        self.config.resolve_settings('cancel')
        self.assertEqual(self.media.read_bytes(), before_media)
        self.assertEqual(self.config.local_path.read_bytes(), before_local)
        self.config.update({'thread_number': 7})
        self.assertEqual(self.media.read_bytes(), before_media)
        self.assertEqual(self.context.Config(self.host.mw).thread_number, 7)
        reopened = self.context.Config(self.host.mw)
        reopened.update({'thread_number': 8})
        self.assertEqual(self.media.read_bytes(), before_media)

    def test_sync_replaces_shared_values_but_never_imports_paths(self):
        self.config.update({'dirs': ['local'], 'dicts': {'a': {'dict_path': 'local.mdx', 'enabled': False}},
                            'ai_markdown': True, 'obsolete': True})
        self.write_media({'dirs': ['foreign'], 'last_folder': 'foreign',
                          'dicts': {'a': {'dict_path': 'foreign.mdx', 'enabled': True}}, 'ai_markdown': False})
        before_media = self.media.read_bytes()
        self.config.resolve_settings('sync')
        self.assertEqual(self.media.read_bytes(), before_media)
        self.assertEqual(self.config.dirs, ['local'])
        self.assertEqual(self.config.dicts['a']['dict_path'], 'local.mdx')
        self.assertTrue(self.config.dicts['a']['enabled'])
        self.assertFalse(self.config.ai_markdown)
        self.assertNotIn('obsolete', self.config.data)
        self.assertEqual(self.config.settings_difference(), [])

    def test_overwrite_publishes_local_values_without_paths_and_preserves_previous(self):
        self.config.update({'ai_markdown': True, 'dirs': ['local']})
        self.write_media({'ai_markdown': False})
        self.config.resolve_settings('overwrite')
        self.assertTrue(json.loads(self.media.read_text())['ai_markdown'])
        self.assertNotIn('dirs', json.loads(self.media.read_text()))
        self.assertFalse(json.loads(self.config.local_path.with_suffix('.previous.json').read_text())['settings']['ai_markdown'])
        self.assertEqual(self.config.settings_difference(), [])

    def test_bad_media_cannot_reset_local_config(self):
        self.config.update({'ai_markdown': True})
        before = deepcopy(self.config.data)
        self.media.write_text('{bad json')
        with self.assertRaises(ValueError):
            self.config.settings_difference()
        with self.assertRaises(ValueError):
            self.config.resolve_settings('sync')
        self.assertEqual(self.config.data, before)
        reopened = self.context.Config(self.host.mw)
        self.assertEqual(reopened.data, before)
        reopened.update({'thread_number': 6})
        self.assertEqual(self.media.read_text(), '{bad json')

    def test_import_is_local_until_overwrite_and_ignores_keys_and_paths(self):
        self.config.update({'dirs': ['local'], 'ai_markdown': True})
        previous_media = self.media.read_bytes()
        self.config.import_settings({'dirs': ['foreign'], 'keys': {'id': 'secret'}, 'ai_markdown': False})
        self.assertEqual(self.media.read_bytes(), previous_media)
        self.assertEqual(self.config.dirs, ['local'])
        self.assertNotIn('keys', self.config.data)
        self.assertFalse(self.config.ai_markdown)
        with self.assertRaises(ValueError):
            self.config.import_settings({'ai_settings': {'profiles': 'bad'}})
        for invalid in ({}, {'profiles': []}, {'unrelated': 'file'}, {'1': {'list': ['invalid']}}):
            with self.assertRaises(ValueError):
                self.config.import_settings(invalid)

    def test_unified_ai_settings_sync_but_credentials_remain_in_profile(self):
        store = self.host.load('service.ai_store')
        store.config = self.config
        profile = {'id': 'demo', 'name': 'Demo', 'model': 'test'}
        store.write_settings({'profiles': [profile], 'keys': {'demo': 'local-secret'}, 'requests_per_minute': 30})
        self.assertEqual(json.loads(self.media.read_text())['credential_backup']['demo'], 'local-secret')
        self.assertEqual(json.loads(self.media.read_text())['ai_settings']['profiles'], [profile])
        self.assertTrue(store.settings_path().is_relative_to(Path(self.host.mw.pm.profileFolder())))
        self.write_media({'ai_settings': {'profiles': [dict(profile, name='Remote')], 'requests_per_minute': 15}})
        self.config.resolve_settings('sync')
        settings = store.read_settings()
        self.assertEqual(settings['profiles'][0]['name'], 'Remote')
        self.assertEqual(settings['requests_per_minute'], 15)
        self.assertEqual(settings['keys']['demo'], 'local-secret')
        self.write_media({})
        self.config.resolve_settings('sync')
        self.assertEqual(store.read_settings()['profiles'], [])
        self.assertEqual(self.context.Config(self.host.mw).ai_settings['profiles'], [])

    def test_parameter_schema_keys_are_not_mistaken_for_credentials_or_paths(self):
        parameters = {'schema': {'properties': {'path': {'type': 'string'}, 'keys': {'type': 'array'}}}}
        self.assertEqual(self.storage.portable({'parameters': parameters})['parameters'], parameters)

    def test_sync_to_another_api_origin_does_not_reuse_local_key(self):
        store = self.host.load('service.ai_store')
        store.config = self.config
        profile = {'id': 'demo', 'name': 'Demo', 'model': 'test', 'base_url': 'https://original.test/responses'}
        store.write_settings({'profiles': [profile], 'keys': {'demo': 'local-secret'}})
        self.write_media({'ai_settings': {'profiles': [dict(profile, base_url='https://different.test/responses')]}})
        self.config.resolve_settings('sync')
        self.assertNotIn('demo', store.read_settings()['keys'])
        self.assertEqual(json.loads(store.settings_path().read_text())['keys']['demo'], 'local-secret')

    def test_first_upgrade_reads_legacy_ai_without_writing_or_deleting_it(self):
        store = self.host.load('service.ai_store')
        profile = {'id': 'demo', 'name': 'Demo', 'model': 'test', 'base_url': 'https://example.test/responses'}
        account = Path(self.host.mw.pm.profileFolder())
        legacy_root = account/'old-plugin'
        legacy = legacy_root/'service/ai'/account.name/'config.json'
        self.storage.atomic_write(legacy, {'profiles': [profile], 'keys': {'demo': 'legacy-secret'}})
        original = legacy.read_bytes()
        with patch.object(self.context, '__file__', str(legacy_root/'context.py')):
            fresh = self.context.Config(self.host.mw)
        self.assertEqual(fresh.ai_settings['profiles'], [profile])
        self.assertNotIn('legacy-secret', json.dumps(fresh.data))
        self.assertFalse(fresh.local_path.exists())
        self.assertFalse(self.media.exists())
        store.config, store.AI_ROOT = fresh, legacy_root/'service/ai'
        current = store.read_settings()
        self.assertEqual(current['keys']['demo'], 'legacy-secret')
        store.write_settings(current)
        self.assertEqual(legacy.read_bytes(), original)
        self.assertTrue(store.settings_path().exists())
        fresh.resolve_settings('overwrite')
        self.assertEqual(json.loads(self.media.read_text())['credential_backup']['demo'], 'legacy-secret')
