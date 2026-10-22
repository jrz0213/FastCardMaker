"""OS credentials are local, API-origin scoped, and absent from every archive."""
import json
import ctypes
from pathlib import Path
import sys
import unittest
import uuid
import zipfile
from unittest.mock import patch
from unittest.mock import Mock
import test_modularization as support


class CredentialTests(unittest.TestCase):
    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.load = self.host.load
        self.store = self.load('service.ai_store')
        self.profile = {'id': 'demo', 'name': 'Demo', 'model': 'test', 'base_url': 'https://example.test/responses'}

    def test_saved_key_is_only_in_system_vault_and_survives_restart(self):
        self.store.write_settings({'profiles': [self.profile], 'keys': {'demo': 'test-secret-value'}})
        self.assertEqual(self.store.settings_path().suffix, '.json')
        metadata = self.store.settings_path().read_text(encoding='utf-8')
        self.assertNotIn('test-secret-value', metadata)
        self.assertNotIn('keys', json.loads(metadata))
        self.assertEqual(self.store.read_settings()['keys']['demo'], 'test-secret-value')
        self.load('service.ai_config').clear_session_keys()
        self.assertEqual(self.load('service.ai_keys').read_keys()['demo'], 'test-secret-value')

    def test_key_is_not_exported_even_with_old_backup_flag_enabled(self):
        backup = self.load('utils.backup_store')
        destination = Path(self.host.mw.pm.profileFolder()) / 'export.zip'
        backup.write_bundle(destination, settings={'ai_settings': {'profiles': [self.profile]},
            'backup_api_keys': True, 'credential_backup': {'demo': 'test-secret'}})
        bundle = backup.read_bundle(destination)
        self.assertNotIn('credential_backup', bundle['settings'])
        with zipfile.ZipFile(destination) as archive:
            self.assertNotIn(b'test-secret', archive.read('settings.json'))

    def test_local_settings_and_backup_are_separate_files(self):
        self.store.write_settings({'profiles': [self.profile], 'keys': {}})
        path = self.store.settings_path()
        edited = json.loads(path.read_text(encoding='utf-8'))
        edited['profiles'][0]['name'] = 'Edited locally'
        path.write_text(json.dumps(edited), encoding='utf-8')
        self.host.config.ai_settings = None
        self.assertEqual(self.store.read_settings()['profiles'][0]['name'], 'Edited locally')
        backup = self.load('utils.backup_store')
        destination = path.parent / 'backup.zip'
        backup.write_bundle(destination, settings={'ai_settings': edited},
                            scripts={'demo.py': {'source': 'value = 1\n'}})
        bundle = backup.read_bundle(destination)
        self.assertEqual(bundle['settings']['ai_settings'], edited)
        self.assertEqual(bundle['scripts']['demo.py']['source'], 'value = 1\n')
        self.assertEqual(json.loads(path.read_text(encoding='utf-8')), edited)

    def test_retired_local_zip_is_not_loaded(self):
        path = self.store.settings_path().with_suffix('.zip')
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('settings.json', json.dumps({'profiles': [self.profile]}))
        self.assertIsNone(self.load('utils.ai_archive').read_cache())

    def test_multiple_api_configs_and_renaming_keep_independent_credentials(self):
        second = dict(self.profile, id='second', name='Work')
        self.store.write_settings({'profiles': [self.profile, second], 'keys': {'demo': 'personal-key', 'second': 'work-key'}})
        self.store.write_settings({'profiles': [dict(self.profile, name='Renamed'), second],
                                   'keys': {'demo': 'personal-key', 'second': 'work-key'}})
        self.assertEqual(self.store.read_settings()['keys'], {'demo': 'personal-key', 'second': 'work-key'})

    def test_clean_replacement_cannot_erase_backup_if_key_migration_fails(self):
        path = Path(self.host.mw.pm.profileFolder()) / 'legacy.zip'
        with zipfile.ZipFile(path, 'w') as archive:
            archive.writestr('settings.json', json.dumps({'ai_settings': {'profiles': [self.profile]},
                'credential_backup': {'demo': 'do-not-delete'}}))
        before = path.read_bytes()
        with patch.object(self.load('utils.system_password'), 'write', side_effect=OSError('locked')):
            with self.assertRaises(OSError):
                self.load('utils.backup_store').write_bundle(path, settings={'ai_settings': {'profiles': []}})
        self.assertEqual(path.read_bytes(), before)

    def test_system_write_failure_preserves_old_key_and_metadata(self):
        self.store.write_settings({'profiles': [self.profile], 'keys': {'demo': 'old-secret'}})
        before = self.store.settings_path().read_bytes()
        system = self.load('utils.system_password')
        original = system.write.side_effect
        def fail_new(value, identifier=''):
            if value == 'new-secret':
                raise OSError('simulated system refusal')
            return original(value, identifier)
        with patch.object(system, 'write', side_effect=fail_new):
            with self.assertRaises(ValueError):
                self.store.write_settings({'profiles': [self.profile], 'keys': {'demo': 'new-secret'}})
        self.assertEqual(self.store.settings_path().read_bytes(), before)
        self.assertEqual(self.store.read_settings()['keys']['demo'], 'old-secret')

    def test_new_device_and_different_origin_do_not_reuse_key(self):
        self.store.write_settings({'profiles': [self.profile], 'keys': {'demo': 'original-secret'}})
        changed = dict(self.profile, base_url='https://other.test/responses')
        self.host.config.ai_settings = {'profiles': [changed]}
        self.assertEqual(self.store.read_settings()['keys'], {})
        self.host.config.ai_settings = {'profiles': [self.profile]}
        self.host.credentials.clear()  # Simulated other device OS vault.
        self.assertEqual(self.store.read_settings()['keys'], {})

    def test_legacy_plaintext_moves_to_os_vault_after_explicit_save(self):
        legacy = self.store.settings_path().with_name('config.json')
        legacy.parent.mkdir(parents=True)
        legacy.write_text(json.dumps({'profiles': [self.profile], 'keys': {'demo': 'legacy-secret'}}))
        self.store.write_settings(self.store.read_settings())
        self.store.remove_legacy_settings()
        self.assertFalse(legacy.exists())
        self.assertEqual(self.store.read_settings()['keys']['demo'], 'legacy-secret')

    def test_automatic_migration_cleans_plaintext_backup_and_preserves_script(self):
        root = Path(self.host.mw.pm.profileFolder())
        media = root / 'collection.media'
        media.mkdir()
        backup = media / '_fastcm_20260101.zip'
        settings = {'ai_settings': {'profiles': [self.profile]}, 'credential_backup': {'demo': 'old-backup-secret'}}
        with zipfile.ZipFile(backup, 'w') as archive:
            archive.writestr('settings.json', json.dumps(settings))
            archive.writestr('scripts/demo.py', 'value = 123\n')
        self.host.config.read = Mock()
        migration = self.load('service.ai_support.migration')
        self.assertEqual(migration.migrate_plaintext(), 1)
        with zipfile.ZipFile(backup) as archive:
            self.assertNotIn(b'old-backup-secret', archive.read('settings.json'))
            self.assertEqual(archive.read('scripts/demo.py'), b'value = 123\n')
        self.assertEqual(self.load('service.ai_support.credentials').read(self.profile), 'old-backup-secret')

    def test_failed_migration_keeps_original_backup(self):
        media = Path(self.host.mw.pm.profileFolder()) / 'collection.media'
        media.mkdir()
        backup = media / '_fastcm_20260101.zip'
        with zipfile.ZipFile(backup, 'w') as archive:
            archive.writestr('settings.json', json.dumps({'ai_settings': {'profiles': [self.profile]},
                'credential_backup': {'demo': 'keep-if-system-refuses'}}))
        before = backup.read_bytes()
        with patch.object(self.load('utils.system_password'), 'write', side_effect=OSError('locked')):
            self.assertEqual(self.load('service.ai_support.migration').migrate_plaintext(), 0)
        self.assertEqual(backup.read_bytes(), before)

    def test_legacy_scripts_zip_is_not_a_credential_backup_and_still_loads(self):
        media = Path(self.host.mw.pm.profileFolder()) / 'collection.media'
        media.mkdir()
        backup = media / '_fastcm_scripts.zip'
        with zipfile.ZipFile(backup, 'w') as archive:
            archive.writestr('legacy.py', 'value = 123\n')
        before = backup.read_bytes()
        migration = self.load('service.ai_support.migration')
        with patch.object(migration.logger, 'warning') as warning:
            self.assertEqual(migration.migrate_plaintext(), 0)
        warning.assert_not_called()
        self.assertEqual(backup.read_bytes(), before)
        self.assertEqual(self.load('service.script_backup').read_backup(),
                         {'legacy.py': {'source': 'value = 123\n'}})

    @unittest.skipUnless(sys.platform == 'win32', 'Windows API only')
    def test_native_windows_vault_roundtrip_with_throwaway_credential(self):
        system = self.load('utils.system_password')
        identifier = 'test-only/' + uuid.uuid4().hex
        try:
            self.assertIsNone(system._windows(identifier=identifier))
            system._windows('throwaway-test-value', 'write', identifier)
            self.assertEqual(system._windows(identifier=identifier), 'throwaway-test-value')
        finally:
            system._windows(operation='delete', identifier=identifier)
        self.assertIsNone(system._windows(identifier=identifier))

    def test_macos_keychain_read_write_update_delete_contract(self):
        system = self.load('utils.system_password')
        security, core = Mock(), Mock()
        state = {'value': None, 'buffer': None}
        def find(*args):
            if state['value'] is None:
                return -25300
            state['buffer'] = ctypes.create_string_buffer(state['value'])
            args[5]._obj.value = len(state['value'])
            args[6]._obj.value = ctypes.addressof(state['buffer'])
            args[7]._obj.value = 123
            return 0
        def add(*args):
            state['value'] = args[6]
            return 0
        def update(*args):
            state['value'] = args[3]
            return 0
        def delete(*args):
            state['value'] = None
            return 0
        security.SecKeychainFindGenericPassword.side_effect = find
        security.SecKeychainAddGenericPassword.side_effect = add
        security.SecKeychainItemModifyAttributesAndData.side_effect = update
        security.SecKeychainItemDelete.side_effect = delete
        with patch.object(system.c, 'CDLL', side_effect=lambda path: security if 'Security.framework' in path else core):
            self.assertIsNone(system._mac(identifier='sample'))
            system._mac('first', 'write', 'sample')
            self.assertEqual(system._mac(identifier='sample'), 'first')
            system._mac('second', 'write', 'sample')
            self.assertEqual(system._mac(identifier='sample'), 'second')
            system._mac(operation='delete', identifier='sample')
            self.assertIsNone(system._mac(identifier='sample'))
        self.assertTrue(core.CFRelease.called)


if __name__ == '__main__':
    unittest.main()
