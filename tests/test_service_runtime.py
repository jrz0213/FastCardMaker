"""Optional service checks using actual HTTP, HTML, and StarDict libraries."""

import importlib.util
import json
import os
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import test_modularization as support

AVAILABLE = all(importlib.util.find_spec(name) for name in ('requests', 'bs4'))
if AVAILABLE:
    import requests
    import bs4


@unittest.skipUnless(AVAILABLE, 'requests and beautifulsoup4 are not installed')
class ServiceRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        sys.modules['requests'] = requests
        sys.modules['bs4'] = bs4
        self.load = self.host.load
        sys.modules[support.PACKAGE + '.utils'].wrap_css = self.load('utils.helper').wrap_css
        del sys.modules[support.PACKAGE + '.utils.fuzzy_match']
        self.load('utils.fuzzy_match')

    def test_actual_html_parser_and_inline_style_wrapper(self):
        base = self.load('service.base')
        soup = base.parse_html('<div><b>hello</b></div>')
        self.assertEqual(soup.find('b').text, 'hello')

        class Dictionary(base.Service):
            @base.export(['Definition'])
            @base.with_styles(css='b { color: red; }', need_wrap_css=True, wrap_class='entry')
            def definition(self):
                return '<b>hello</b>'

        result = Dictionary().active(0, 'hello').result
        self.assertIn('.entry b', result)
        self.assertIn('<div class="entry"><b>hello</b></div>', result)

    def test_real_stardict_files_and_builder(self):
        del sys.modules[support.PACKAGE + '.libs']
        libs = self.load('libs')
        base = self.load('service.base')
        with tempfile.TemporaryDirectory() as temp:
            prefix = Path(temp) / 'sample'
            definition = b'first line\nsecond line'
            index = b'hello\0' + struct.pack('!II', 0, len(definition))
            prefix.with_suffix('.dict').write_bytes(definition)
            prefix.with_suffix('.idx').write_bytes(index)
            prefix.with_suffix('.ifo').write_text(
                "StarDict's dict ifo file\nversion=2.4.2\nbookname=Test\n"
                f'wordcount=1\nidxfilesize={len(index)}\nsametypesequence=m\n', encoding='utf-8')
            builder = libs.StardictBuilder(str(prefix), in_memory=False)
            try:
                with patch.object(base.LocalService, '_get_builder', return_value=builder):
                    service = base.StardictService(str(prefix.with_suffix('.ifo')))
                self.assertEqual(service.active(0, 'hello').result, 'first line<br />second line')
                self.assertEqual(service.active(0, 'missing').result, '')
            finally:
                builder.dict._file.close()

    def test_mdx_media_and_css_files_with_actual_wrapper(self):
        base = self.load('service.base')
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            source = directory / 'dict'
            media = directory / 'media'
            source.mkdir()
            media.mkdir()
            (source / 'sample.mdx').touch()
            (source / 'theme.css').write_text('b { color: red; }', encoding='utf-8')
            (source / 'pic.png').write_bytes(b'image')
            service = base.MdxService('missing.mdx')
            service.dict_path = str(source / 'sample.mdx')
            service.media_dir = str(media)
            service.builder = Mock()
            service.builder.get_mdd_keys.return_value = []
            previous = Path.cwd()
            try:
                os.chdir(media)
                html = service.adapt_to_anki('<link href="theme.css"><img src="pic.png"><b>word</b>')
            finally:
                os.chdir(previous)
            image_name = service.media_name('pic.png')
            css_name = service.media_name('theme.css')
            wrapped = css_name[:-4] + '_wrap.css'
            self.assertEqual((media / image_name).read_bytes(), b'image')
            self.assertTrue((media / wrapped).is_file())
            self.assertIn('.' + css_name[:-4] + ' b', (media / wrapped).read_text())
            self.assertIn('src="' + image_name + '"', html)

    def test_real_fuzzy_audio_replaces_complete_anchor(self):
        base = self.load('service.base')
        service = base.MdxService('missing.mdx')
        service.builder = Mock()
        self.host.config.fuzzy_match = True
        service.builder.get_mdd_keys.side_effect = lambda pattern: [] if pattern == '*\\hello-us.mp3' else ['\\hello_us.ogg']
        with patch.object(service, 'save_default_file', return_value='fixed.ogg'), patch.object(service, 'save_media_files'):
            html = service.adapt_to_anki('<div><a href="sound:hello-us.mp3">Play</a></div>')
        self.assertEqual(html, '<div>[sound:fixed.ogg]</div>')

    def test_all_bundled_dictionary_modules_import(self):
        utils = sys.modules[support.PACKAGE + '.utils']
        utils.ignore_exception = self.load('utils.misc').ignore_exception
        sys.modules['aqt.utils'].showText = Mock()
        base = self.load('service.base')
        for path in sorted((support.SRC / 'service' / 'dict').glob('*.py')):
            if path.name == '__init__.py':
                continue
            with self.subTest(dictionary=path.stem):
                dictionary = self.load('service.dict.' + path.stem)
                classes = [value for value in vars(dictionary).values()
                           if isinstance(value, type) and value.__module__ == dictionary.__name__
                           and issubclass(value, base.Service)]
                self.assertTrue(classes)

    def test_ai_prompt_expands_real_html_fields_once(self):
        ai = self.load('service.ai')
        self.assertEqual(ai.render_prompt('Explain {{Word}}: {{例句}}', {
            'Word': '<b>hello</b>', '例句': 'A &amp; B<br>second line',
        }), 'Explain hello: A & B\nsecond line')
        # Placeholders inside field content must not be expanded recursively.
        self.assertEqual(ai.render_prompt('{{Word}}', {'Word': '{{Other}}', 'Other': 'secret'}), '{{Other}}')

    def test_combined_ai_expands_html_then_splits_json_tables(self):
        settings = self.load('service.ai_config')
        profile = settings.new_profile('custom')
        profile.update(base_url='https://example.test/v1', model='test', send_mode='note')
        settings.save_profiles([profile], {profile['id']: 'test-key'})
        ai = self.load('service.ai')
        text = json.dumps({'意思': '**苹果**', '相似词': '| 单词 | 关系 |\n| --- | --- |\n| pear | 同类词 |'})
        response = Mock(status_code=200)
        response.json.return_value = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
        with patch.object(ai, '_send', return_value=response) as send:
            results = ai.query_ai_many('ai:' + profile['id'],
                {'意思': '解释 {{单词}}', '相似词': '对比 {{单词}}，参考 {{例句}}'},
                {'单词': '<b>apple</b>', '例句': 'A &amp; B<br>{{Other}}'})
        tasks = json.loads(send.call_args.args[2]['input'])['tasks']
        self.assertEqual(tasks['意思'], '解释 apple')
        self.assertEqual(tasks['相似词'], '对比 apple，参考 A & B\n{{Other}}')
        self.assertEqual(results['意思'].result, '<p><strong>苹果</strong></p>')
        self.assertIn('<table>', results['相似词'].result)
        self.assertIn('<td>同类词</td>', results['相似词'].result)


if __name__ == '__main__':
    unittest.main()
