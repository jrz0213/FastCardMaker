"""Concurrency, profile isolation, dictionary failures and media regressions."""

import fnmatch
import json
import os
import sys
import tempfile
import threading
import time
import types
import unittest
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock, patch

import test_ai
import test_modularization as support


class StabilityTests(unittest.TestCase):
    def setUp(self):
        self.host = test_ai.AITests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.load = self.host.load
        self.common = self.host.query_module()
        self.config = self.host.host.config
        self.base = self.load('service.base')
        self.local = self.load('service.local')
        self.Pool = self.load('service.pool').ServicePool

    def pool(self, factory):
        return self.Pool(types.SimpleNamespace(get_service=factory))

    def test_folder_script_sync_is_background_ready_and_preserves_config(self):
        scripts = self.load('service.custom_scripts')
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            external, internal = root / 'external', root / 'internal'
            external.mkdir()
            internal.mkdir()
            dictionary = external / 'sample.mdx'
            dictionary.touch()
            (external / 'sample.py').write_text(
                "DICT_PATH = ''\n@register(['Sample'])\nclass Sample(Service): pass\n", encoding='utf-8')
            (internal / 'removed.py').write_text(
                "DICT_PATH = r'C:/removed/sample.mdx'\n", encoding='utf-8')
            (internal / 'web.py').write_text('class Web: pass\n', encoding='utf-8')
            before = deepcopy(self.config.dicts)
            enabled = scripts.sync_folder_scripts([str(external)], str(internal), lambda: False)
            self.assertEqual(enabled, {'Sample'})
            self.assertIn(dictionary.as_posix(), (internal / 'sample.py').read_text(encoding='utf-8'))
            self.assertFalse((internal / 'removed.py').exists())
            self.assertTrue((internal / 'web.py').exists())
            self.assertEqual(self.config.dicts, before)
            self.config.update.assert_not_called()

    def test_pool_reserves_slots_before_concurrent_initialization(self):
        created = []
        lock = threading.Lock()
        def factory(unique):
            time.sleep(0.01)
            service = types.SimpleNamespace(unique=unique)
            with lock:
                created.append(service)
            return service
        pool = self.pool(factory)
        gate = threading.Barrier(12)
        def query(_):
            gate.wait(timeout=2)
            with pool.borrow('same', timeout=2) as service:
                self.assertIsNotNone(service)
                time.sleep(0.02)
        with ThreadPoolExecutor(max_workers=12) as executor:
            list(executor.map(query, range(12)))
        self.assertLessEqual(len(created), 5)
        self.assertEqual(pool.instance_counts['same'], len(created))
        self.assertEqual(pool.pools['same'].qsize(), len(created))

    def test_pool_cancel_timeout_reset_and_late_returns(self):
        pool = self.pool(lambda unique: types.SimpleNamespace(unique=unique))
        held = [pool.get('same') for _ in range(5)]
        self.assertIsNone(pool.get('same', timeout=0.01))
        cancelled = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(pool.get, 'same', cancelled.is_set)
            cancelled.set()
            self.assertIsNone(future.result(timeout=0.5))
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(pool.get, 'same')
            time.sleep(0.02)
            pool.clean()
            self.assertIsNone(future.result(timeout=0.5))
        fresh = pool.get('same')
        for old in held:
            pool.put(old)
        self.assertEqual(pool.instance_counts['same'], 1)
        self.assertEqual(pool.pools['same'].qsize(), 0)
        pool.put(fresh)
        pool.put(fresh)
        self.assertEqual(pool.pools['same'].qsize(), 1)

    def test_pool_factory_failure_and_exception_inside_lease_release_capacity(self):
        factory = Mock(side_effect=RuntimeError('initialization failed'))
        pool = self.pool(factory)
        with self.assertRaises(RuntimeError):
            pool.get('same')
        self.assertEqual(pool.instance_counts['same'], 0)
        factory.side_effect = None
        factory.return_value = types.SimpleNamespace(unique='same')
        with self.assertRaises(RuntimeError):
            with pool.borrow('same'):
                raise RuntimeError('query failed')
        self.assertIs(pool.get('same'), factory.return_value)

    def test_unsupported_services_are_returned_and_never_clear_fields(self):
        note, maps = self.host.note_and_maps()
        note.fields = ['hello', 'original', 'example']
        maps[1]['dict_unique'] = 'missing'
        self.config.force_update = True
        factory = Mock(return_value=types.SimpleNamespace(unique='missing', support=False))
        pool = self.pool(factory)
        with patch.object(self.common, 'service_pool', pool):
            for _ in range(12):
                results, _, _ = self.common.query_flds(note, mappings=maps, include_ai=False)
                self.assertEqual(self.common.update_note_fields(note, results), 0)
                self.assertTrue(results.errors)
        self.assertEqual(note.fields[1], 'original')
        self.assertEqual(factory.call_count, 1)

    def test_invalid_dictionary_field_cannot_clear_existing_content(self):
        note, maps = self.host.note_and_maps()
        note.fields = ['hello', 'original', 'example']
        self.config.force_update = True
        service = types.SimpleNamespace(unique='local', support=True, fields=('Definition',), active=Mock())
        maps[1].update(dict_unique='local', dict_fld_ord=99)
        with patch.object(self.common, 'service_pool', self.pool(lambda _: service)):
            results, _, _ = self.common.query_flds(note, mappings=maps, include_ai=False)
        self.assertTrue(results.errors)
        self.assertEqual(self.common.update_note_fields(note, results), 0)
        self.assertEqual(note.fields[1], 'original')
        service.active.assert_not_called()

    def test_opposite_dictionary_orders_do_not_hold_multiple_leases(self):
        def factory(unique):
            service = types.SimpleNamespace(unique=unique, support=True)
            def active(*args):
                time.sleep(0.005)
                return self.base.QueryResult(result=unique)
            service.active = active
            return service
        pool = self.pool(factory)
        pool.MAX_INSTANCES = 1
        def query(index):
            note, maps = self.host.note_and_maps()
            note.fields = ['hello', '', '']
            order = ['A', 'B'] if index % 2 else ['B', 'A']
            maps = [maps[0]] + [dict(fld_ord=i, dict_fld_ord=0, dict_unique=unique)
                                 for i, unique in enumerate(order, 1)]
            return self.common.query_flds(note, mappings=maps, include_ai=False)[1]
        with patch.object(self.common, 'service_pool', pool), ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(query, index) for index in range(8)]
            self.assertEqual([future.result(timeout=2) for future in futures], [2] * 8)

    def test_building_and_failed_mdx_and_stardict_preserve_force_updated_fields(self):
        note, maps = self.host.note_and_maps()
        note.fields = ['hello', 'original', 'example']
        self.config.force_update = True
        with tempfile.TemporaryDirectory() as temp:
            for suffix, cls in (('.mdx', self.base.MdxService), ('.ifo', self.base.StardictService)):
                path = Path(temp) / ('sample' + suffix)
                path.touch()
                with patch.object(self.local.LocalService, '_get_builder', return_value=None):
                    service = cls(str(path))
                service.unique = 'dictionary'
                maps[1]['dict_unique'] = 'dictionary'
                key = self.local.LocalService.builder_key(path)
                for status in ('checking', 'building', 'failed'):
                    self.local.LocalService._build_status[key] = status
                    with patch.object(self.local.LocalService, '_get_builder', return_value=None), \
                            patch.object(self.common, 'service_pool', self.pool(lambda _: service)):
                        results, _, _ = self.common.query_flds(note, mappings=maps, include_ai=False)
                    self.assertEqual(self.common.update_note_fields(note, results), 0)
                    self.assertTrue(results.errors)
                    self.assertEqual(note.fields[1], 'original')

    def test_failed_builder_state_and_explicit_retry_are_deduplicated(self):
        local = self.local.LocalService
        worker_class = self.local._DictBuilderQueueThread
        factory = Mock(side_effect=ValueError('bad file'))
        with patch.object(self.local, '_DictBuilderQueueThread', return_value=Mock()):
            local._get_builder('broken.mdx', factory)
            job = local._build_queue.get_nowait()
            queue = Mock()
            queue.get.side_effect = [job, SystemExit]
            worker = worker_class(queue, local._mdx_builders, local._build_status, local._mutex_builder)
            with self.assertRaises(SystemExit):
                worker.run()
            self.assertEqual(local.get_db_status('broken.mdx'), 'failed')
            local._get_builder('broken.mdx', factory)
            self.assertEqual(local._build_queue.qsize(), 0)
            self.assertTrue(local.retry_build('broken.mdx'))
            self.assertFalse(local.retry_build('broken.mdx'))
            self.assertEqual(local._build_queue.qsize(), 1)
            self.assertEqual(local.get_db_status('broken.mdx'), 'checking')

    def config_class(self):
        self.host.host.mw.pm.name = 'Test'
        hooks = types.ModuleType('anki.hooks')
        hooks.runHook = Mock()
        sys.modules['anki.hooks'] = hooks
        sys.modules[support.PACKAGE + '.constants'].VERSION = 'test'
        del sys.modules[support.PACKAGE + '.context']
        return self.load('context').Config

    def test_profile_configs_use_absolute_paths_and_reload_on_switch(self):
        Config = self.config_class()
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                a, b = Path(temp) / 'A', Path(temp) / 'B'
                for folder, word in ((a, 'first'), (b, 'second')):
                    (folder / 'collection.media').mkdir(parents=True)
                    (folder / 'collection.media' / '_fastwqcfg.json').write_text(json.dumps({'dirs': [word]}))
                window = types.SimpleNamespace(pm=types.SimpleNamespace(name='A', profileFolder=lambda: str(a)))
                config = Config(window)
                generation = config.generation
                os.chdir(b)
                config.update({'test': 'A-only'})
                self.assertEqual(json.loads((a / 'collection.media' / '_fastcmcfg.json').read_text())['test'], 'A-only')
                self.assertNotIn('test', json.loads((a / 'collection.media' / '_fastwqcfg.json').read_text()))
                window.pm.name = 'B'
                window.pm.profileFolder = lambda: str(b)
                config.read()
                self.assertEqual(config.dirs, ['second'])
                self.assertGreater(config.generation, generation)
                self.assertNotIn('test', config.data)
                self.assertTrue(os.path.isabs(config.path))
            finally:
                os.chdir(previous)

    def test_failed_atomic_config_write_keeps_previous_file_and_data(self):
        Config = self.config_class()
        config = Config(self.host.host.mw)
        config.update({'test': 'original'})
        before = Path(config.path).read_bytes()
        with patch('os.replace', side_effect=OSError('disk error')), self.assertRaises(OSError):
            config.update({'test': 'changed'})
        self.assertEqual(config.data['test'], 'original')
        self.assertEqual(Path(config.path).read_bytes(), before)

    def test_old_ai_result_is_discarded_after_profile_generation_changes(self):
        self.config.generation = 0
        sys.modules['aqt.qt'].QApplication = types.SimpleNamespace(processEvents=Mock())
        sys.modules['aqt.qt'].QMessageBox = Mock()
        module = self.load('query.ai_runner')
        note, maps = self.host.note_and_maps()
        runner = module.AIQueryRunner([note], mappings=maps, model=note.note_type(), writer=Mock())
        self.config.generation = 1
        runner.apply(runner.tasks[0], self.base.QueryResult(result='stale'))
        self.assertEqual(note.fields[1], 'old')
        runner.writer.assert_not_called()

    def test_cloze_preserves_attributes_scripts_styles_entities_and_existing_clozes(self):
        html = ('<DIV class="hello" data-value="hello > hello">hello</DIV>\n'
                '<script>var hello = "hello";</script><style>.hello{color:red}</style>'
                '<!-- hello -->&amp; hello {{c1::<b>hello</b>::hello}} [sound:hello.mp3]')
        expected = ('<DIV class="hello" data-value="hello > hello">{{c1::hello}}</DIV>\n'
                    '<script>var hello = "hello";</script><style>.hello{color:red}</style>'
                    '<!-- hello -->&amp; {{c1::hello}} {{c1::<b>hello</b>::hello}} [sound:hello.mp3]')
        self.assertEqual(self.common.cloze_deletion(html, 'hello'), expected)
        self.assertEqual(self.common.cloze_deletion(expected, 'hello'), expected)

    def media_service(self, path, media, values=None):
        service = self.base.MdxService('missing.mdx')
        service.dict_path, service.media_dir = str(path), str(media)
        values = values or {}
        service.builder = types.SimpleNamespace(
            mdd_lookup=lambda key, **kwargs: [values[key]] if key in values else [],
            get_mdd_keys=lambda pattern: [key for key in values if fnmatch.fnmatchcase(key, pattern)])
        return service

    def test_media_names_separate_spaces_directories_and_dictionaries(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values = {'\\a b.png': b'space', '\\a-b.png': b'dash',
                      '\\first\\pic.png': b'first', '\\second\\pic.png': b'second'}
            a = self.media_service(root / 'a.mdx', root / 'media', values)
            b = self.media_service(root / 'b.mdx', root / 'media', values)
            names = [a.save_default_file(resource) for resource in values]
            self.assertEqual(len(set(names)), 4)
            self.assertEqual([(root / 'media' / name).read_bytes() for name in names], list(values.values()))
            self.assertNotEqual(a.media_name('a b.png'), b.media_name('a b.png'))
            self.assertEqual(a.media_name('a%20b.png'), a.media_name('a b.png'))

    def test_css_dependencies_and_js_imports_follow_namespaced_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            values = {'\\css\\theme.css': b'@import "../extra.css"; b{background:url("../img/pic.png")} @font-face{src:url("../font.woff")}',
                      '\\extra.css': b'i{color:red}', '\\img\\pic.png': b'image', '\\font.woff': b'font',
                      '\\scripts\\main.js': b'import "./extra.js";', '\\scripts\\extra.js': b'export const value=1;'}
            service = self.media_service(root / 'sample.mdx', root / 'media', values)
            service.save_default_file('css/theme.css')
            css = (root / 'media' / service.media_name('css/theme.css')).read_text()
            for resource in ('extra.css', 'img/pic.png', 'font.woff'):
                self.assertIn(service.media_name(resource), css)
                self.assertTrue((root / 'media' / service.media_name(resource)).is_file())
            name = service.save_default_file('scripts/main.js')
            self.assertIn('./' + service.media_name('scripts/extra.js'), (root / 'media' / name).read_text())

    def test_media_writes_use_captured_profile_even_when_cwd_changes(self):
        previous = Path.cwd()
        with tempfile.TemporaryDirectory() as temp:
            try:
                root = Path(temp)
                (root / 'B').mkdir()
                service = self.media_service(root / 'sample.mdx', root / 'A', {'\\pic.png': b'first-profile'})
                os.chdir(root / 'B')
                name = service.save_default_file('pic.png')
                self.assertEqual((root / 'A' / name).read_bytes(), b'first-profile')
                self.assertFalse((root / 'B' / name).exists())
            finally:
                os.chdir(previous)

    def test_sound_double_slash_links_write_and_reference_the_same_media(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            service = self.media_service(root / 'sample.mdx', root / 'media', {'\\folder\\hello.mp3': b'audio'})
            html = service.adapt_to_anki('<a href="sound://folder/hello.mp3">Play</a>')
            name = service.media_name('folder/hello.mp3')
            self.assertEqual(html, '[sound:' + name + ']Play')
            self.assertEqual((root / 'media' / name).read_bytes(), b'audio')

    def test_default_mdx_renames_static_audio_but_does_not_evaluate_js_audio_paths(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            script = b'function play(word) { return new Audio("audio/en/" + word + ".mp3").play(); }'
            service = self.media_service(root / 'sample.mdx', root / 'media', {
                '\\scripts\\play.js': script, '\\audio\\en\\hello.mp3': b'original audio'})
            dynamic = service.adapt_to_anki('<script src="scripts/play.js"></script><a onclick="play(\'hello\')">Play</a>')
            js_name = service.media_name('scripts/play.js')
            audio_name = service.media_name('audio/en/hello.mp3')
            self.assertIn(js_name, dynamic)
            self.assertEqual((root / 'media' / js_name).read_bytes(), script)
            self.assertFalse((root / 'media' / audio_name).exists())
            static = service.adapt_to_anki('<a href="sound:audio/en/hello.mp3">Play</a>')
            self.assertIn('[sound:' + audio_name + ']', static)
            self.assertTrue(audio_name.startswith('_fcm_'))
            self.assertEqual((root / 'media' / audio_name).read_bytes(), b'original audio')

    def manager(self):
        sys.modules['aqt'].gui_hooks = types.SimpleNamespace(profile_did_open=[])
        sys.modules['aqt.qt'].QTimer = Mock()
        module = self.load('service.manager')
        return module, module.ServiceManager.__new__(module.ServiceManager)

    def test_custom_script_fallback_checks_initialization_and_full_dictionary_path(self):
        module, manager = self.manager()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            a, b = root / 'A', root / 'B'
            a.mkdir(); b.mkdir()
            for folder in (a, b):
                (folder / 'same.mdx').touch()
            class Valid(self.base.MdxService):
                __register_label__ = 'Valid'
                def __init__(self):
                    super().__init__(str(a / 'same.mdx'))
            class Broken(self.base.MdxService):
                __register_label__ = 'Broken'
                def __init__(self):
                    raise RuntimeError('bad custom parser')
            custom = types.ModuleType(support.PACKAGE + '.service.dict.sample')
            Valid.__module__ = Broken.__module__ = custom.__name__
            custom.Valid, custom.Broken = Valid, Broken
            self.config.dicts = {'Valid': {'enabled': True}, 'Broken': {'enabled': True}}
            self.config.dirs = [str(a), str(b)]
            with patch.object(module.os, 'listdir', return_value=['sample.py']), \
                    patch.object(module.importlib, 'import_module', return_value=custom), \
                    patch.object(self.local.LocalService, '_get_builder', return_value=object()):
                manager.web_services, manager.local_custom_services, loaded = manager._get_services_from_files()
            manager.local_services = manager.local_custom_services
            self.assertIsNone(manager.get_service('Broken'))
            mdx, _ = manager._get_available_local_services(loaded)
            self.assertEqual(len(mdx), 1)
            with patch.object(self.local.LocalService, '_get_builder', return_value=None):
                self.assertEqual(mdx[0]().dict_path, str(b / 'same.mdx'))
            self.config.dicts['Valid']['enabled'] = False
            self.assertEqual(len(manager._get_available_local_services(loaded)[0]), 2)

    def test_generated_adapter_keeps_default_mdx_registered_when_enabled(self):
        module, manager = self.manager()
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'pure.mdx'
            path.touch()
            class Generated(self.base.MdxService):
                __register_label__ = 'Generated'
                __keep_default_mdx__ = True
                def __init__(self):
                    super().__init__(str(path))
            custom = types.ModuleType(support.PACKAGE + '.service.dict.generated')
            Generated.__module__ = custom.__name__
            custom.Generated = Generated
            self.config.dicts = {'Generated': {'enabled': True}}
            self.config.dirs = [temp]
            with patch.object(module.os, 'listdir', return_value=['generated.py']), \
                    patch.object(module.importlib, 'import_module', return_value=custom), \
                    patch.object(self.local.LocalService, '_get_builder', return_value=object()):
                manager.web_services, manager.local_custom_services, loaded = manager._get_services_from_files()
            self.assertEqual(len(manager._get_available_local_services(loaded)[0]), 1)
            self.assertEqual(manager.local_custom_services[0].__dict_path__, str(path))

    def test_external_script_path_resyncs_even_if_next_profiles_script_is_older(self):
        module, manager = self.manager()
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            external = root / 'profile-B'
            external.mkdir()
            (external / 'sample.mdx').touch()
            (external / 'sample.py').write_text("DICT_PATH = r'old.mdx'\nclass Sample: pass\n", encoding='utf-8')
            internal = root / 'addon' / 'service' / 'dict'
            internal.mkdir(parents=True)
            (internal / 'sample.py').write_text("DICT_PATH = r'profile-A/sample.mdx'\nclass Sample: pass\n", encoding='utf-8')
            os.utime(internal / 'sample.py', (time.time() + 10, time.time() + 10))
            self.config.dirs = [str(external)]
            realpath = os.path.realpath
            with patch.object(module.os.path, 'realpath', side_effect=lambda path:
                              str(root / 'addon' / 'service' / 'manager.py') if path == module.__file__ else realpath(path)):
                manager._sync_external_scripts()
            content = (internal / 'sample.py').read_text(encoding='utf-8')
            self.assertIn(str(external / 'sample.mdx').replace('\\', '/'), content)
            self.config.update.assert_not_called()

    def test_service_rescan_invalidates_only_dictionary_script_modules(self):
        module, manager = self.manager()
        prefix = support.PACKAGE + '.service.dict'
        sys.modules[prefix + '.old'] = types.ModuleType(prefix + '.old')
        other = prefix + '_unrelated'
        sys.modules[other] = types.ModuleType(other)
        with patch.object(manager, '_sync_external_scripts'), \
                patch.object(manager, '_get_services_from_files', return_value=([], [], set())), \
                patch.object(manager, '_get_available_local_services', return_value=([], [])):
            manager.update_services()
        self.assertNotIn(prefix + '.old', sys.modules)
        self.assertIn(other, sys.modules)


if __name__ == '__main__':
    unittest.main()
