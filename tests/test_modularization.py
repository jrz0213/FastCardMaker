"""Regression checks that run without an installed Anki or Qt runtime.

Only host and third-party boundaries are replaced; the extracted modules are
imported and exercised directly. Run: python -m unittest discover -s tests -v
"""

import importlib
import logging
import sys
import tempfile
import types
import unittest
from hashlib import md5
from pathlib import Path
from unittest.mock import Mock, patch


SRC = Path(__file__).resolve().parents[1] / 'src'
PACKAGE = '_fwq_refactor_tests'


class HostObject:
    def __init__(self, *args, **kwargs):
        pass


class RefactorTests(unittest.TestCase):
    def setUp(self):
        self.modules = {}

        def add(name, path=None, **attrs):
            value = types.ModuleType(name)
            value.__dict__.update(attrs)
            if path is not None:
                value.__path__ = [str(path)]
            self.modules[name] = value
            return value

        add(PACKAGE, SRC)
        add(PACKAGE + '.service', SRC / 'service', service_manager=Mock(), service_pool=Mock())
        add(PACKAGE + '.gui', SRC / 'gui')
        utils = add(PACKAGE + '.utils', SRC / 'utils', wrap_css=Mock(), get_icon=Mock())
        add(PACKAGE + '.utils.logger', logger=logging.getLogger('refactor_tests'))
        add(PACKAGE + '.utils.fuzzy_match', process_fuzzy_media=Mock(return_value={}))
        self.config = types.SimpleNamespace(
            sound_str='[sound:{0}]', use_filename=True, ignore_mdx_wordcase=True,
            fuzzy_match=False, export_media=True, dicts={}, update=Mock(),
            settings_difference=Mock(return_value=[]), resolve_settings=Mock(),
        )
        add(PACKAGE + '.context', config=self.config)
        add(PACKAGE + '.lang', _cl=lambda labels: labels[0],
            _=lambda label: label, _sl=lambda label: ['MDX_SERVER'])
        add(PACKAGE + '.libs', MdxBuilder=Mock(), StardictBuilder=Mock())
        add(PACKAGE + '.constants', Endpoint=types.SimpleNamespace(user_guide='guide'))
        self.mw = types.SimpleNamespace()
        profile_dir = tempfile.TemporaryDirectory()
        self.addCleanup(profile_dir.cleanup)
        self.mw.pm = types.SimpleNamespace(profileFolder=lambda: profile_dir.name)
        add('aqt', mw=self.mw)
        qt = add('aqt.qt', QObject=HostObject, QThread=HostObject, QMutex=Mock,
                 pyqtSignal=lambda *args: Mock(), QIcon=Mock, QApplication=Mock())
        for name in ['QComboBox', 'QTabBar', 'QScrollArea', 'QLayout', 'QSize', 'QRect', 'QSizePolicy']:
            setattr(qt, name, HostObject)
        qt.Qt = types.SimpleNamespace(ItemFlag=types.SimpleNamespace(ItemIsEnabled=1))
        add('aqt.utils', showInfo=Mock())
        add('requests', Session=Mock(), get=Mock(), post=Mock(),
            RequestException=type('RequestException', (Exception,), {}))
        add('bs4', BeautifulSoup=Mock())
        add(PACKAGE + '.gui.base', Dialog=HostObject, WIDGET_SIZE=Mock())
        add(PACKAGE + '.gui.setting', SettingDialog=Mock())
        add(PACKAGE + '.gui.options_controller', OptionsController=Mock())
        self.module_patch = patch.dict(sys.modules, self.modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.load('service.ai_store').AI_ROOT = Path(profile_dir.name) / 'service' / 'ai'
        # Use the actual mapping dictionary implementation, without utils/__init__.
        utils.MapDict = self.load('utils.misc').MapDict

    def load(self, name):
        return importlib.import_module(PACKAGE + '.' + name)

    def test_compatibility_exports_share_class_and_decorator_identity(self):
        base = self.load('service.base')
        for name, target in [('Service', 'core'), ('WebService', 'web'),
                             ('LocalService', 'local'), ('MdxService', 'mdx'),
                             ('StardictService', 'stardict'), ('QueryResult', 'result')]:
            self.assertIs(getattr(base, name), getattr(self.load('service.' + target), name))
        self.assertIs(base.export, self.load('service.helpers').export)
        namespace = {}
        exec('from ' + PACKAGE + '.service.base import *', namespace)
        self.assertEqual(set(base.__all__), set(namespace) - {'__builtins__'})
        self.assertIsNotNone(self.mw.dict_signals.status_changed)

    def test_export_order_inheritance_and_query_result(self):
        base = self.load('service.base')

        @base.register(['Parent'])
        class Parent(base.Service):
            @base.export(['First'])
            def z_first(self):
                return self.word

        @base.register(['Child'])
        class Child(Parent):
            @base.export(['Second'])
            def a_second(self):
                return base.QueryResult(result=None)

        service = Child()
        self.assertEqual(service.fields, ('First', 'Second'))
        self.assertEqual(base.service_wrap(Child).__fields__, service.fields)
        self.assertEqual(service.active(0, '<b>hello</b>').result, 'hello')
        self.assertEqual(service.active(1, 'hello').result, '')
        self.assertEqual(service.active(99, 'hello').result, '')
        result = base.QueryResult.default()
        result.set_styles(js='script')
        self.assertEqual(result.js, 'script')

    def test_local_builder_queue_deduplicates_and_exposes_status(self):
        local = self.load('service.local')
        service = local.LocalService
        key = 'dictionary.mdx'
        digest = service.builder_key(key)
        thread = Mock()
        with patch.object(local, '_DictBuilderQueueThread', return_value=thread):
            factory = Mock()
            self.assertIsNone(service._get_builder(key, factory))
            self.assertIsNone(service._get_builder(key, factory))
            self.assertEqual(service._build_queue.qsize(), 1)
            thread.start.assert_called_once()
            self.assertEqual(service.get_db_status(key), 'checking')
            builder = object()
            service._mdx_builders[digest] = builder
            service._build_status[digest] = 'ready'
            self.assertIs(service._get_builder(key), builder)
            self.assertEqual(service.get_db_status(key), 'ready')

    def test_builder_worker_updates_shared_cache_and_signals(self):
        local = self.load('service.local')
        queue = Mock()
        builder = object()
        queue.get.side_effect = [(lambda: builder, 'hash'), SystemExit]
        builders, statuses, mutex = {}, {}, Mock()
        worker = local._DictBuilderQueueThread(queue, builders, statuses, mutex)
        with self.assertRaises(SystemExit):
            worker.run()
        self.assertIs(builders['hash'], builder)
        self.assertEqual(statuses['hash'], 'ready')
        queue.task_done.assert_called_once()
        self.assertEqual(self.mw.dict_signals.status_changed.emit.call_args_list,
                         [unittest.mock.call('hash', 'building'),
                          unittest.mock.call('hash', 'ready')])

    def test_web_get_post_and_download_requirements(self):
        service = self.load('service.base').WebService()
        response = Mock(status_code=200, content=b'audio',
                        headers={'Content-Type': 'audio/mpeg'})
        service.session.get.return_value = response
        service.session.post.return_value = response
        self.assertEqual(service.net_stream([('https://example.test', {'word': 'a b'})],
                                            require={'mime': 'audio', 'size': 3}), b'audio')
        self.assertEqual(service.session.get.call_args.args[0],
                         'https://example.test?word=a%20b')
        self.assertEqual(service.get_response('url', data={'word': 'hello'}), b'audio')
        service.session.post.assert_called_once()
        with self.assertRaises(IOError):
            service.net_stream('url', require={'size': 100})

    def test_mdx_lookup_redirect_and_media_extraction(self):
        base = self.load('service.base')
        with tempfile.TemporaryDirectory() as temp:
            dictionary = Path(temp) / 'sample.mdx'
            dictionary.touch()
            with patch.object(base.LocalService, '_get_builder', return_value=Mock()):
                service = base.MdxService(str(dictionary))
            service.word = 'hello'
            service.builder.mdx_lookup.side_effect = lambda word, **kwargs: {
                'hello': ['@@@LINK=target'], 'target': ['definition'],
            }.get(word, [])
            with patch.object(service, 'adapt_to_anki', side_effect=lambda html: html):
                self.assertEqual(service.get_default_html(), 'definition')
                self.assertEqual(service.get_default_html(), 'definition')
                self.assertEqual(service.builder.mdx_lookup.call_count, 2)
            service.builder.mdd_lookup.return_value = [b'audio data']
            service.builder.get_mdd_keys.return_value = ['\\a b.mp3']
            destination = Path(temp) / 'audio.mp3'
            self.assertEqual(service.save_default_file('\\a b.mp3', str(destination)), str(destination))
            self.assertEqual(destination.read_bytes(), b'audio data')
            with patch.object(service, 'save_media_files') as save:
                html = service.adapt_to_anki('<a href="sound:a b.mp3">Play</a>')
            self.assertEqual(html, '[sound:' + service.media_name('a b.mp3') + ']Play')
            save.assert_called_once_with({'a b.mp3'})

    def test_stardict_builder_key_and_newline_conversion(self):
        base = self.load('service.base')
        with tempfile.TemporaryDirectory() as temp:
            dictionary = Path(temp) / 'sample.ifo'
            dictionary.touch()
            with patch.object(base.LocalService, '_get_builder', return_value={'hello': 'a\nb'}) as get:
                service = base.StardictService(str(dictionary))
            self.assertEqual(get.call_args.args[0], str(dictionary)[:-4])
            self.assertEqual(service.active(0, 'hello').result, 'a<br />b')
            self.assertEqual(service.active(0, 'missing').result, '')

    def test_mdx_fuzzy_media_uses_subclass_save_hook(self):
        base = self.load('service.base')

        class CustomDictionary(base.MdxService):
            def save_default_file(self, name, savepath=None):
                return 'custom-file'

        service = CustomDictionary('missing.mdx')
        service.builder = Mock()
        service.builder.get_mdd_keys.return_value = []
        self.config.fuzzy_match = True
        fuzzy = self.load('utils.fuzzy_match').process_fuzzy_media
        fuzzy.return_value = {'missing.png': '<img src="_fixed.png">'}
        with patch.object(service, 'save_media_files'):
            html = service.adapt_to_anki('<img src="missing.png">')
        self.assertEqual(html, '<img src="_fixed.png">')
        self.assertEqual(fuzzy.call_args.args[3], service.save_default_file)

    def test_mapping_choices_keep_status_and_selected_dictionary(self):
        controls = self.load('gui.mapping_controls')
        combo = Mock()
        entries = []
        combo.addItem.side_effect = lambda label, userData: entries.append((label, userData))
        combo.count.side_effect = lambda: len(entries)
        combo.itemData.side_effect = lambda index: entries[index][1]
        combo.model.return_value.item.return_value.flags.return_value = 3
        selected = controls.fill_dict_combo_options(None, combo, 'ready', {
            'local': [{'title': 'Building', 'unique': 'building', 'status': 'building'},
                      {'title': 'Ready', 'unique': 'ready', 'status': 'ready'}],
            'web': [{'title': 'Online', 'unique': 'online'}],
        })
        self.assertTrue(selected)
        combo.setCurrentIndex.assert_called_with(1)
        combo.model.return_value.item.return_value.setFlags.assert_called_once_with(2)
        combo.insertSeparator.assert_called_once_with(2)
        self.assertEqual([unique for _, unique in entries], ['building', 'ready', 'online'])
        host = types.SimpleNamespace(_controller=Mock())
        host._controller.get_service_fields.return_value = ['Definition', 'Audio']
        fields = Mock()
        controls.fill_field_combo_options(host, fields, 'Ready', 'ready', 'Audio', 1)
        fields.setCurrentIndex.assert_called_with(1)

    def test_custom_script_adaptation_and_enable_config(self):
        scripts = self.load('service.custom_scripts')
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / 'sample.py'
            script.write_text("from plugin.service.base import MdxService\n"
                              "DICT_PATH = r'old.mdx'\n@register([u'', u''])\n"
                              "class Sample(MdxService):\n    pass\n", encoding='utf-8')
            target = Path(temp) / 'dict'
            scripts.process_and_copy_custom_py('C:/dict/sample.mdx', str(script), str(target))
            copied = (target / 'sample.py').read_text(encoding='utf-8')
            self.assertIn("DICT_PATH = r'C:/dict/sample.mdx'", copied)
            self.assertIn('from ..base import MdxService', copied)
            self.assertIn("u'MDX-sample'", copied)
            self.assertTrue(self.config.dicts['Sample']['enabled'])

    def test_gui_imports_compatibility_and_unbuilt_mapping_data(self):
        options = self.load('gui.options')
        self.assertIs(options.TabContent, self.load('gui.options_tab').TabContent)
        self.assertIs(options.CTabBar, self.load('gui.options_widgets').CTabBar)
        self.load('gui.dictmanager')
        folders = self.load('gui.foldermanager')
        self.assertIs(folders.process_and_copy_custom_py,
                      self.load('service.custom_scripts').process_and_copy_custom_py)
        tab = options.TabContent.__new__(options.TabContent)
        tab._was_built = False
        tab._conf = [{'fld_name': 'Meaning'}]
        self.assertEqual(tab.data, tab._conf)
        event = Mock()
        options.NoScrollComboBox().wheelEvent(event)
        event.ignore.assert_called_once()


if __name__ == '__main__':
    unittest.main()
