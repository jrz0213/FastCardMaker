"""Portable dictionary binding and script archive checks using temporary files."""
from pathlib import Path
import struct
import zlib
import unittest
from unittest.mock import patch
import zipfile
import test_modularization as support


def mdx(path, title):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = ('<Dictionary Title="' + title + '" Encoding="UTF-8"/>\0').encode('utf-16')
    path.write_bytes(struct.pack('>I', len(data)) + data + struct.pack('<I', zlib.adler32(data)))


class PortableScriptTests(unittest.TestCase):
    def test_bundled_mdx_parsers_have_filename_bindings_without_local_paths(self):
        for name in ('LDOCE5.py', 'LDOCE6.py', 'TLD.py', 'oaldpe.py', '百词斩图解词典.py'):
            source = (support.SRC / 'service' / 'dict' / name).read_text(encoding='utf-8')
            binding = self.binding.source_binding(source)
            self.assertTrue(binding['file'], name)
            self.assertEqual(binding['title'], '')
            self.assertNotIn('BaiduYunDownload', source)

    def test_filename_only_nested_match_and_legacy_path_priority(self):
        old = self.root / 'old' / 'Oxford.mdx'
        current = self.root / 'new' / '1' / '2' / 'Oxford.mdx'
        mdx(old, 'Old title')
        mdx(current, 'New title')
        with self.binding.use_catalogue(self.binding.Catalogue([self.root / 'new'])):
            self.assertEqual(self.binding.resolve_dictionary('Oxford.mdx', legacy_path=str(old)), str(current.resolve()))
        with self.binding.use_catalogue(self.binding.Catalogue([])):
            self.assertEqual(self.binding.resolve_dictionary('Oxford', legacy_path=str(old)), str(old.resolve()))
        self.assertEqual(self.binding.source_binding("DICT_FILE='Oxford.mdx'"), {'file': 'Oxford', 'title': ''})

    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.binding = self.host.load('service.dictionary_binding')
        self.root = Path(self.host.mw.pm.profileFolder())
        self.backup = self.host.load('service.script_backup')
        self.library = self.host.load('service.script_library')
        self.scripts = self.library.script_directory()
        self.scripts.mkdir(parents=True)

    def test_header_and_binding_survive_move_but_reject_duplicate_or_changed_title(self):
        first = self.root / 'a' / 'Oxford.mdx'
        mdx(first, 'Oxford &amp; Examples')
        binding = self.binding.descriptor(first)
        self.assertEqual(binding, {'file': 'Oxford', 'title': 'Oxford & Examples'})
        second = self.root / 'b' / first.name
        second.parent.mkdir()
        first.rename(second)
        self.assertEqual(self.binding.identity(binding), self.binding.identity(self.binding.descriptor(second)))
        catalogue = self.binding.Catalogue([self.root])
        self.assertEqual(catalogue.candidates(binding), [str(second.resolve())])
        with self.binding.use_catalogue(catalogue):
            self.assertEqual(self.binding.resolve_dictionary(**{'filename': 'Oxford', 'title': binding['title']}), str(second.resolve()))
        mdx(first, 'Oxford &amp; Examples')
        with self.binding.use_catalogue(self.binding.Catalogue([self.root])):
            self.assertIn('__fastcm_unavailable__', self.binding.resolve_dictionary('Oxford', binding['title']))
        mdx(first, 'Other edition')
        self.assertEqual(self.binding.Catalogue([self.root]).candidates(binding), [str(second.resolve())])

    def test_legacy_source_is_path_free_idempotent_and_keeps_class(self):
        path = self.root / 'Oxford.mdx'
        mdx(path, 'Oxford')
        source = "DICT_PATH = " + repr(str(path)) + "\nclass Original: pass\n"
        result = self.binding.portable_source(source)
        self.assertEqual(result, source)  # Legacy path constants remain usable.
        self.assertIn('class Original', result)
        self.assertEqual(result, self.binding.portable_source(result))

    def test_digest_order_and_same_size_content_change(self):
        left = {'a.py': {'source': 'x=1'}, 'b.py': {'source': 'x=2'}}
        self.assertEqual(self.backup.digest(left), self.backup.digest(dict(reversed(list(left.items())))))
        self.assertNotEqual(self.backup.digest(left), self.backup.digest(dict(left, **{'a.py': {'source': 'x=3'}})))

    def test_first_backup_is_python_only_and_roundtrips(self):
        (self.scripts / 'one.py').write_text('x=1', encoding='utf-8')
        (self.scripts / 'chat.json').write_text('{}')
        local, remote = self.backup.initialize()
        self.assertIsNone(remote)
        self.assertEqual(self.backup.read_backup(), local)
        with zipfile.ZipFile(self.backup.backup_path()) as archive:
            self.assertEqual(set(archive.namelist()), {'manifest.json', 'settings.json', 'scripts/one.py'})

    def test_unicode_script_names_are_included(self):
        (self.scripts / '百词斩.py').write_text('value=1', encoding='utf-8')
        self.backup.initialize()
        self.assertIn('百词斩.py', self.backup.read_backup())

    def test_local_edit_publishes_but_external_change_does_not_get_overwritten(self):
        path = self.scripts / 'one.py'
        path.write_text('x=1')
        self.backup.initialize()
        path.write_text('x=2')
        self.assertTrue(self.backup.auto_publish())
        self.assertEqual(self.backup.read_backup()['one.py']['source'], 'x=2')
        self.backup.write_backup({'one.py': {'source': 'x=3'}})
        path.write_text('x=4')
        self.assertFalse(self.backup.auto_publish())
        self.assertEqual(self.backup.read_backup()['one.py']['source'], 'x=3')

    def test_selection_handles_delete_add_and_stale_confirmation(self):
        (self.scripts / 'one.py').write_text('x=1')
        local, _ = self.backup.initialize()
        remote = {'two.py': {'source': 'x=2'}}
        self.backup.write_backup(remote)
        self.backup.apply_selection(remote, self.backup.digest(local), self.backup.digest(remote))
        self.assertFalse((self.scripts / 'one.py').exists())
        self.assertTrue((self.scripts / 'two.py').exists())
        self.assertTrue(list((self.scripts / '.fwq-trash').glob('*.bak')))
        with self.assertRaises(ValueError):
            self.backup.apply_selection(local, self.backup.digest(local), self.backup.digest(remote))

    def test_zip_traversal_and_invalid_python_rejected_without_extraction(self):
        self.backup.backup_path().parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(self.backup.backup_path(), 'w') as archive:
            archive.writestr('../outside.py', 'x=1')
        with self.assertRaises(ValueError):
            self.backup.read_backup()
        self.assertFalse((self.root / 'outside.py').exists())
