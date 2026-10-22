"""Three raw MDX samples, bounded extraction rules and trusted adapters."""
import ast
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import py_compile
import types
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import Mock, patch

try:
    import bs4 as real_bs4
    from bs4 import BeautifulSoup as real_soup
except ImportError:
    real_soup = None
import test_gui_runtime as gui_runtime
import test_modularization as support


@unittest.skipUnless(real_soup and importlib.util.find_spec('PyQt6'), 'Qt/BeautifulSoup not installed')
class ScriptGenerationTests(unittest.TestCase):
    def test_third_turn_splits_local_feedback_and_deduplicates_current_script(self):
        information = self.host.load('service.script_information')
        source = 'def parser():\n    return "value"\n'
        first_reply = json.dumps({'message': 'script one', 'code': source})
        second_reply = json.dumps({'message': 'explanation only'})
        records = [
            {'id': 'one', 'kind': 'request', 'user_message': 'first question', 'response': first_reply,
             'request': {'samples': [{'html': 'never repeat this old attachment'}]},
             'local': {'validation': 'passed', 'generated_script': source}},
            {'id': 'debug-one', 'kind': 'debug', 'error': 'missing-image-unique'},
            {'id': 'two', 'kind': 'request', 'user_message': 'second question', 'response': second_reply,
             'request': {'local_information': [{'error': 'must not recursively repeat'}]}}
        ]
        history, notes = information.selected_context(records)
        self.assertEqual([turn['role'] for turn in history], ['user', 'assistant', 'user', 'assistant'])
        self.assertEqual([turn['content'] for turn in history], ['first question', first_reply, 'second question', second_reply])
        self.assertEqual(len(notes), 2)
        request = information.deduplicate_scripts({'user_message': 'third question',
            'current_script': {'source': source}, 'original_scripts': [{'name': 'parser.py', 'source': source}],
            'local_information': notes}, history)
        self.assertNotIn('source', request['current_script'])
        self.assertNotIn('source', request['original_scripts'][0])
        self.assertNotIn('generated_script', request['local_information'][0]['data'])
        for mode in ('chat', 'responses', 'messages'):
            profile = dict(self.host.load('service.ai_config').new_profile('custom'), model='test',
                base_url='https://example.test/custom', interface_format=mode)
            payload = self.host.load('service.ai').request_payload(profile, json.dumps(request), history=history)
            turns = payload['input' if mode == 'responses' else 'messages']
            self.assertEqual(len(turns), 5)
            self.assertEqual(sum(turn['content'] == first_reply for turn in turns), 1)
            self.assertEqual(json.dumps(payload).count('missing-image-unique'), 1)
            self.assertNotIn('never repeat this old attachment', json.dumps(payload))
            self.assertNotIn('must not recursively repeat', json.dumps(payload))
        selected_history, selected_notes = information.selected_context(records, {'0-assistant', '1-debug'})
        self.assertEqual(selected_history, [{'role': 'assistant', 'content': first_reply}])
        self.assertEqual(len(selected_notes), 1)
        self.assertEqual(selected_notes[0]['kind'], 'debug')
        self.assertEqual(information.selected_context(records, set()), ([], []))

    def test_generation_and_chat_both_respect_history_selection(self):
        module = self.host.load('gui.script_generator')
        for chat in (False, True):
            for selected in (False, True):
                with self.subTest(chat=chat, selected=selected):
                    dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
                    self.host.widgets.append(dialog)
                    dialog.add_information({'kind': 'request', 'user_message': 'earlier question',
                                            'request': {}, 'response': 'earlier reply'})
                    if selected:
                        dialog.send_selected.setChecked(True)
                        dialog.toggle_message(module.QUrl('select:0-assistant'))
                    with patch.object(module, 'ScriptOperationThread'), \
                            patch.object(module, 'Generation', wraps=module.Generation) as generation:
                        dialog._begin_request('follow up' if chat else '')
                    expected = [{'role': 'assistant', 'content': 'earlier reply'}]
                    if not selected:
                        expected.insert(0, {'role': 'user', 'content': 'earlier question'})
                    self.assertEqual(generation.call_args.kwargs['history'], expected)
                    dialog.loader = None

    def test_output_help_only_explains_the_two_formats(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        content = []
        def inspect_help(window):
            content.append(window.findChild(module.QTextBrowser).toPlainText())
        with patch.object(module.Dialog, 'exec', inspect_help):
            dialog.show_output_help()
        self.assertIn('勾选（默认）', content[0])
        self.assertIn('不勾选', content[0])
        self.assertNotIn('信息历史', content[0])
        self.assertLess(len(content[0]), 240)

    def test_history_paths_are_hidden_and_messages_are_counted_individually(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        fake = types.SimpleNamespace(support=True, builder=self.builder)
        local_root = str(Path('sample.mdx').resolve().parent)
        history = [{'role': 'user', 'content': local_root + '/parser.py'},
                   {'role': 'assistant', 'content': 'earlier reply'},
                   {'role': 'user', 'content': json.dumps({'traceback': local_root + '\\parser.py'})}]
        with patch.object(base, 'MdxService', return_value=fake), \
                patch.object(module, 'request_ai_text', return_value=json.dumps(self.rules)) as request:
            result = module.Generation('sample.mdx', 'ai:test', [], self.names, history=history).load_services()
        self.assertNotIn('error', result, result)
        sent = request.call_args.kwargs['history']
        self.assertNotIn(local_root, sent[0]['content'])
        self.assertIn('parser.py', sent[0]['content'])
        self.assertNotIn(json.dumps(local_root)[1:-1], sent[2]['content'])
        self.assertEqual(result['record']['context']['history_messages'], 3)
        self.assertEqual(history[0]['content'], local_root + '/parser.py')

    def test_python_response_is_checked_without_execution_and_prompts_follow_mode(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        source = '''from ..base import MdxService, register, export
raise RuntimeError('must not run during generation')
@register(['Example', 'Example'])
class Example(MdxService):
    @export(['Nested', 'Nested'])
    def nested(self):
        return '<section><ul><li>Nested content</li></ul></section>'
'''
        fake = types.SimpleNamespace(support=True, builder=self.builder)
        for message in ('', 'Please revise the nested structure'):
            with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text', return_value='```python\n' + source + '```') as request:
                with patch.object(module, 'debug_exports', side_effect=AssertionError('must not auto execute')):
                    result = module.Generation('sample.mdx', 'ai:test', [], None, 'Extract', message=message,
                                               debug=True, return_json=False).load_services()
            self.assertNotIn('error', result, result)
            self.assertEqual(result['format'], 'python')
            self.assertEqual(result['source'], source)
            self.assertEqual(request.call_args.args[2], module.PYTHON_INSTRUCTIONS)
            self.assertNotIn('debug_record', result)
        with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text', return_value=json.dumps(self.rules)) as request:
            module.Generation('sample.mdx', 'ai:test', [], self.names, return_json=True).load_services()
        self.assertEqual(request.call_args.args[2], module.INSTRUCTIONS)

    def test_python_mode_checkbox_disables_automatic_execution(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        self.assertTrue(dialog.return_json.isChecked())
        dialog.return_json.setChecked(False)
        self.assertFalse(hasattr(dialog, 'auto_debug'))
        self.assertFalse(hasattr(dialog, 'cancel_button'))
        self.assertEqual(dialog.debug_button.text(), '调试')
        dialog.return_json.setChecked(True)
        self.assertTrue(dialog.return_json.isChecked())

    def test_import_text_selection_and_recycle_list(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        path = Path(self.temp.name) / 'conversation.md'
        content = 'User: previous question\nAI: complete previous reply\n<script>not executable</script>'
        path.write_text(content, encoding='utf-8')
        with patch.object(module.QFileDialog, 'getOpenFileName', return_value=(str(path), '')):
            dialog.import_conversation()
        self.assertIn(content, dialog.conversation.toPlainText())
        self.assertIn(content, module.compact_history(dialog.conversations)[0]['content'])
        self.assertIn(datetime.now().strftime('%Y-%m-%d'), dialog.conversation.toPlainText())
        dialog.toggle_message(module.QUrl('select:0-user'))
        dialog.copy_selected_information()
        self.assertIn(content, self.host.app.clipboard().text())
        updates = self.host.load('service.script_updates')
        source = Path(self.temp.name) / 'example.py'
        source.write_text('x = 1', encoding='utf-8')
        updates.recycle_script(source, self.temp.name)
        recycle = self.host.load('gui.script_recycle').ScriptRecycleDialog(dialog, self.temp.name)
        self.host.widgets.append(recycle)
        self.assertEqual(recycle.files.count(), 1)
        self.assertIn('example.py', recycle.files.item(0).text())
        self.assertIn(datetime.now().strftime('%Y-%m-%d'), recycle.files.item(0).text())
        self.assertTrue(recycle.open_button.isEnabled())
        recycle.accept()
        restored = updates.restore_script(recycle.selected_path, self.temp.name)
        self.assertEqual(Path(restored).read_text(encoding='utf-8'), 'x = 1')

    def test_history_all_or_selected_defaults_and_new_messages_are_unchecked(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        dialog.add_information({'kind': 'request', 'user_message': 'question',
                                'request': {'html': 'attachment not repeated'}, 'response': 'answer'})
        self.assertTrue(dialog.send_history.isChecked())
        self.assertFalse(dialog._selected_messages)
        self.assertEqual(dialog.selected_history(), [{'role': 'user', 'content': 'question'},
                                                     {'role': 'assistant', 'content': 'answer'}])
        dialog.send_selected.setChecked(True)
        self.assertFalse(dialog.send_history.isChecked())
        self.assertEqual(dialog.selected_history(), [])
        dialog.toggle_message(module.QUrl('select:0-assistant'))
        self.assertEqual(dialog.selected_history(), [{'role': 'assistant', 'content': 'answer'}])
        dialog.add_information({'kind': 'debug', 'passed': True, 'rows': []})
        self.assertNotIn('1-debug', dialog._selected_messages)
        self.assertEqual(dialog.selected_history(), [{'role': 'assistant', 'content': 'answer'}])

    def test_python_structure_validation_rejects_invalid_or_renamed_scripts(self):
        parser = self.host.load('service.python_scripts')
        for source in ('{"fields": []}', 'def invalid(:', '@register(["X"])\nclass X(object): pass'):
            with self.assertRaises((SyntaxError, ValueError)):
                parser.parse_python(source)
        with self.assertRaises(ValueError):
            parser.parse_python('@register(["X"])\nclass New(MdxService): pass', 'Original')

    def test_python_debug_executes_only_when_explicitly_called_and_reports_errors(self):
        module = self.host.load('service.script_debug')
        service, result = self.debug_candidate()
        result.update(format='python', class_name='Example', source='''from ..base import MdxService, register, export
raise RuntimeError('explicit debug execution')
@register(['Example'])
class Example(MdxService): pass
''')
        report = module.debug_exports(service, result)
        self.assertFalse(report['passed'])
        self.assertEqual(report['error'], 'explicit debug execution')
        self.assertIn('traceback', report)
        result['source'] = '''from ..base import MdxService, register, export
@register(['Example'])
class Example(MdxService):
    def __init__(self):
        from ..core import Service
        Service.__init__(self)
    def fld_whole(self):
        return ''
    @export(['Nested'])
    def nested(self):
        return '<section><ul><li>' + self.word + '</li></ul></section>'
'''
        report = module.debug_exports(service, result)
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['scope'], 'complete_python_script')
        self.assertEqual(len(report['rows']), 3)
        self.assertIn('<section><ul><li>', report['rows'][0]['result'])

    def test_media_only_rules_keep_all_exports_and_legacy_path_code(self):
        rule = self.audio_rules()['fields'][0]
        rules = {'fields': [], 'unavailable': [], 'media': [{key: rule[key] for key in ('selector', 'audio', 'limit')}]}
        self.assertEqual(self.engine.parse_rules(json.dumps(rules), None), rules)
        updates = self.host.load('service.script_updates')
        source = '''from ..base import *
DICT_PATH = r'C:/legacy/sample.mdx'
@register(['Original'])
class Original(MdxService):
    @export(['Meaning'])
    def meaning(self):
        return 'keep meaning'
    @export(['Audio'])
    def audio(self):
        return self.old_audio_path()
'''
        updated = updates.update_source(source, rules, 'Original')
        def methods(text):
            cls = next(node for node in ast.parse(text).body if isinstance(node, ast.ClassDef))
            return {node.name: ast.dump(node) for node in cls.body if isinstance(node, ast.FunctionDef)}
        self.assertEqual(methods(source), methods(updated))
        self.assertIn("DICT_PATH = r'C:/legacy/sample.mdx'", updated)
        _, adapter = self.engine.render_script('sample.mdx', rules)
        self.assertNotIn('@export(', adapter)
        self.assertIn('__media_rules__', adapter)

    def test_optional_media_rule_repairs_audio_without_changing_definition_or_bytes(self):
        from pathlib import Path
        root = Path(self.temp.name)
        (root / 'audio').mkdir()
        payload = b'original unchanged audio'
        (root / 'audio' / 'apple-uk.mp3').write_bytes(payload)
        rule = self.audio_rules()['fields'][0]
        rules = [{key: rule[key] for key in ('selector', 'audio', 'limit')}]
        module = self.host.load('service.media_rules')
        html = '<div class="def">Keep this meaning</div><a class="audio" onclick="playSound(\'apple_uk\')">UK</a>'
        unchanged = module.repair_media(html, [], self.builder, str(root / 'sample.mdx'))
        self.assertEqual(unchanged, html)
        fixed = module.repair_media(html, rules, self.builder, str(root / 'sample.mdx'))
        self.assertIn('Keep this meaning', fixed)
        self.assertIn('sound:audio/apple-uk.mp3', fixed)
        self.assertEqual(module.repair_media(fixed, rules, self.builder, str(root / 'sample.mdx')), fixed)
        self.assertEqual((root / 'audio' / 'apple-uk.mp3').read_bytes(), payload)
        no_change = {'fields': [], 'unavailable': [], 'media': []}
        self.assertEqual(self.engine.parse_rules(json.dumps(no_change), None), no_change)

    def setUp(self):
        gui_runtime.GuiRuntimeTests.setUpClass()
        self.host = gui_runtime.GuiRuntimeTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        sys.modules['bs4'] = real_bs4
        self.engine = self.host.load('service.selector_scripts')
        self.engine.BeautifulSoup = real_soup
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.database = Path(self.temp.name) / 'sample.mdx.db'
        with sqlite3.connect(self.database) as connection:
            connection.execute('create table MDX_INDEX(key_text text)')
            connection.executemany('insert into MDX_INDEX values (?)', [(f'word{i}',) for i in range(36)])
        connection.close()
        self.builder = types.SimpleNamespace(_mdx_db=str(self.database), mdx_lookup=lambda word, **kwargs:
                    [f'<span class="def">Meaning of {word}</span><span class="phon">/{word}/</span>'])
        self.names = ['Meaning', 'Phonetic']
        self.rules = {'fields': [{'name': 'Meaning', 'selector': '.def', 'format': 'text', 'limit': 5},
                                {'name': 'Phonetic', 'selector': '.phon', 'format': 'text', 'limit': 1}],
                      'unavailable': []}
        settings = self.host.load('service.ai_config')
        profile = settings.new_profile('custom')
        profile.update(id='test', model='test-model', base_url='https://example.test/v1/responses')
        self.host.host.config.ai_profiles = [profile]
        settings._session_keys['test'] = 'test-session-key'

    def test_samples_are_three_distinct_entries_spread_across_readonly_index(self):
        samples = self.engine.collect_samples(self.builder)
        self.assertEqual([sample['word'] for sample in samples], ['word0', 'word12', 'word24'])
        prompt = json.loads(self.engine.build_prompt(samples, self.names))
        self.assertEqual(prompt['samples'][0]['html'], samples[0]['html'])
        self.assertIn('class="def"', prompt['samples'][0]['html'])

    def test_manual_words_redirects_missing_and_cancelled_samples(self):
        self.builder.mdx_lookup = lambda word, **kwargs: ['@@@LINK=word2'] if word == 'alias' else ([f'<b>{word}</b>'] if word != 'missing' else [])
        samples = self.engine.collect_samples(self.builder, ['alias', 'word3', 'word4'])
        self.assertEqual(samples[0]['html'], '<b>word2</b>')
        for words in (['word2', 'word2', 'word3'], ['word2', 'word3'], ['missing', 'word3', 'word4']):
            with self.assertRaises(ValueError):
                self.engine.collect_samples(self.builder, words)
        with self.assertRaises(ValueError):
            self.engine.collect_samples(self.builder, ['word2', 'word3', 'word4'], cancelled=lambda: True)
        self.builder.mdx_lookup = lambda word, **kwargs: ['@@@LINK=word2', '<b>variant</b>'] if word == 'alias' else ['<b>target</b>']
        self.assertEqual(self.engine.resolve_entry(self.builder, 'alias'), '<b>target</b>\n<b>variant</b>')

    def test_strict_rules_reject_unknown_fields_bad_selectors_and_code(self):
        self.assertEqual(self.engine.parse_rules(json.dumps(self.rules), self.names), self.rules)
        invalid = ['import os', '{"fields": [], "unavailable": []}',
                   json.dumps(dict(self.rules, unexpected='code')),
                   json.dumps({'fields': [dict(self.rules['fields'][0], selector='[')], 'unavailable': ['Phonetic']}),
                   json.dumps({'fields': [dict(self.rules['fields'][0], limit=True)], 'unavailable': ['Phonetic']})]
        for value in invalid:
            with self.assertRaises(ValueError):
                self.engine.parse_rules(value, self.names)

    def test_preview_requires_actual_content_and_does_not_export_script_tags(self):
        samples = self.engine.collect_samples(self.builder)
        preview = self.engine.validate_samples(samples, self.rules)
        self.assertEqual(preview[0]['fields']['Meaning'], 'Meaning of word0')
        rules = {'fields': [dict(self.rules['fields'][0], selector='.does-not-exist')], 'unavailable': ['Phonetic']}
        with self.assertRaises(ValueError):
            self.engine.validate_samples(samples, rules)
        result = self.engine.extract_field('<div class="def">OK<script>alert(1)</script></div>',
                                           dict(self.rules['fields'][0], format='html'))
        self.assertNotIn('<script', result)
        self.assertIn('OK', result)

    def test_template_compiles_runs_extraction_and_never_overwrites_existing_file(self):
        filename, source = self.engine.render_script(str(Path(self.temp.name) / "dictionary's.mdx"), self.rules)
        tree = ast.parse(source)
        tree.body = [node for node in tree.body if not isinstance(node, (ast.Import, ast.ImportFrom))]
        builder = self.builder
        class Base:
            def __init__(self, path):
                self.builder, self.word, self.dict_path = builder, 'word0', path
            def adapt_to_anki(self, content):
                return 'ADAPTED:' + content
        values = {'resolve_dictionary': lambda filename, title: filename + '.mdx', 'MdxService': Base, 'register': lambda labels: lambda cls: cls,
                  'export': lambda labels: lambda fn: fn, 'json': json,
                  'extract_required': self.engine.extract_required, 'resolve_entry': self.engine.resolve_entry,
                  'adapt_extracted': self.engine.adapt_extracted}
        exec(compile(tree, filename, 'exec'), values)
        generated = next(value for key, value in values.items() if key.startswith('FCMAI_'))
        self.assertTrue(generated.__keep_default_mdx__)
        self.assertEqual(generated().generated_field_0(), 'ADAPTED:Meaning of word0')
        original = builder.mdx_lookup
        builder.mdx_lookup = lambda *args, **kwargs: ['<span class="phon">/missing/</span>']
        with self.assertRaises(ValueError):
            generated().generated_field_0()
        builder.mdx_lookup = original
        path = self.engine.save_script(filename, source, self.temp.name)
        self.assertEqual(Path(path).read_text(encoding='utf-8'), source)
        with self.assertRaises(FileExistsError):
            self.engine.save_script(filename, 'replacement', self.temp.name)
        self.assertEqual(Path(path).read_text(encoding='utf-8'), source)

    def test_generation_sends_html_once_and_returns_unsaved_python_source(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        fake = types.SimpleNamespace(support=True, builder=self.builder)
        with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text', return_value=json.dumps(self.rules)) as request:
            result = module.Generation('sample.mdx', 'ai:test', [], self.names).load_services()
        self.assertNotIn('error', result)
        request.assert_called_once()
        sent = json.loads(request.call_args.args[1])
        self.assertEqual(len(sent['samples']), 3)
        self.assertIn('<span class="def">', sent['samples'][0]['html'])
        self.assertIn('class FCMAI_', result['source'])
        self.assertFalse((Path(self.temp.name) / result['filename']).exists())

    def test_literal_ai_request_never_interpolates_or_strips_source_html(self):
        ai = self.host.load('service.ai')
        raw = '<span class="def">{{Word}}</span>'
        with patch.object(ai, '_request_text', return_value='{}') as request:
            self.assertEqual(ai.request_ai_text('ai:test', raw, 'JSON rules'), '{}')
        self.assertEqual(request.call_args.args[1], raw)

    def test_generator_omits_profile_skill_and_sends_extraction_requirements(self):
        module = self.host.load('gui.script_generator')
        ai = self.host.load('service.ai')
        profile = self.host.load('service.ai_config').new_profile('custom')
        profile.update(id='test', model='test-model', base_url='https://example.test/v1/responses', skill='Normal field Skill must stay saved')
        self.host.host.config.ai_profiles = [profile]
        base = self.host.load('service.base')
        fake = types.SimpleNamespace(support=True, builder=self.builder)
        requirements = '释义只取中文部分；例句取英文原文。'
        with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text', return_value=json.dumps(self.rules)) as request:
            result = module.Generation('sample.mdx', 'ai:test', [], None, requirements).load_services()
        self.assertNotIn('error', result)
        sent = json.loads(request.call_args.args[1])
        self.assertEqual(sent['user_command'], requirements)
        self.assertEqual(sent['requested_fields'], [])
        connection = request.call_args.kwargs['connection']
        self.assertEqual(connection.profile['skill'], '')
        self.assertEqual(connection.profile['model'], 'test-model')
        payload = ai.request_payload(connection.profile, request.call_args.args[1], request.call_args.args[2])
        self.assertEqual(payload['instructions'], self.engine.INSTRUCTIONS)
        self.assertEqual(profile['skill'], 'Normal field Skill must stay saved')
        self.assertEqual(ai.request_payload(profile, 'normal task')['instructions'], profile['skill'])
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        dialog.script_directory = self.temp.name
        dialog.ready(result)
        self.assertEqual(json.loads(dialog.samples_view.toPlainText())['user_command'], requirements)

    def test_extraction_requirements_are_literal_and_bounded_before_send(self):
        samples = self.engine.collect_samples(self.builder)
        requirements = '保留 {{Meaning}} 标签\n只提取 <span> 中的内容'
        prompt = json.loads(self.engine.build_prompt(samples, self.names, command=requirements))
        self.assertEqual(prompt['user_command'], requirements)
        with self.assertRaises(ValueError):
            self.engine.build_prompt(samples, self.names, command='x' * 4001)
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        dialog.command.setPlainText('x' * 4001)
        with patch.object(module, 'Generation') as generation:
            dialog.begin()
            generation.assert_not_called()
        self.assertIn('4000', dialog.status.text())

    def test_command_can_infer_field_names_but_still_validates_schema(self):
        self.assertEqual(self.engine.parse_rules(json.dumps(self.rules), None), self.rules)
        for name in ('', ' ', 'x' * 61):
            invalid = {'fields': [dict(self.rules['fields'][0], name=name)], 'unavailable': []}
            with self.assertRaises(ValueError):
                self.engine.parse_rules(json.dumps(invalid), None)
        invalid = dict(self.rules, unavailable=[f'Other{i}' for i in range(11)])
        with self.assertRaises(ValueError):
            self.engine.parse_rules(json.dumps(invalid), None)

    def test_representative_samples_pick_one_word_from_each_group_and_fall_back(self):
        with sqlite3.connect(self.database) as connection:
            connection.executemany('insert into MDX_INDEX values (?)',
                                   [(word,) for word in ('concept', 'context', 'maintain', 'expand', 'relevant', 'distinct')])
        connection.close()
        samples = self.engine.collect_samples(self.builder)
        self.assertEqual([sample['word'] for sample in samples], ['concept', 'maintain', 'relevant'])
        original = self.builder.mdx_lookup
        self.builder.mdx_lookup = lambda word, **kwargs: [] if word in ('concept', 'maintain') else original(word, **kwargs)
        samples = self.engine.collect_samples(self.builder)
        self.assertEqual([sample['word'] for sample in samples], ['context', 'expand', 'relevant'])

    def test_dialog_defaults_to_command_and_representative_samples(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        self.assertFalse(hasattr(dialog, 'fields'))
        self.assertEqual([edit.text() for edit in dialog.words], ['concept', 'maintain', 'relevant'])
        self.assertIn('仅在需要时修复音频路径', dialog.command.toPlainText())
        dialog.profile_combo.addItem('Test AI', 'ai:test')
        dialog.profile_combo.setCurrentIndex(dialog.profile_combo.findData('ai:test'))
        with patch.object(module, 'Generation') as generation, patch.object(module, 'ScriptOperationThread', return_value=Mock()):
            dialog.begin()
        args = generation.call_args.args
        self.assertEqual(args[2], [])
        self.assertIsNone(args[3])
        self.assertEqual(args[4], dialog.command.toPlainText())

    def test_dialog_preview_and_explicit_save_keep_profile_boundary(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        samples = self.engine.collect_samples(self.builder)
        filename, source = self.engine.render_script('sample.mdx', self.rules)
        result = {'samples': samples, 'rules': self.rules, 'preview': self.engine.validate_samples(samples, self.rules),
                  'filename': filename, 'source': source}
        dialog.ready(result)
        self.assertTrue(dialog.save_button.isEnabled())
        self.assertIn('Meaning of word0', dialog.preview.toPlainText())
        with patch.object(module, 'save_script', return_value=str(Path(self.temp.name) / filename)) as save:
            dialog.save_button.click()
            save.assert_called_once()
            save.reset_mock()
            dialog.token = ('another-profile', 0)
            dialog.save()
            save.assert_not_called()

    def test_pure_mdx_row_has_generation_button_without_enabling_it(self):
        registry = sys.modules[support.PACKAGE + '.service'].service_manager
        registry.local_services = [types.SimpleNamespace(__title__='Pure', __unique__='pure', __path__='',
                                                        __dict_path__='sample.mdx')]
        dialog = self.host.load('gui.dictmanager').DictManageDialog(None)
        self.host.widgets.append(dialog)
        self.assertFalse(dialog._options[0]['generate_btn'].isHidden())
        self.assertFalse(dialog._options[0]['check_btn'].isChecked())

    def audio_rules(self):
        return {'fields': [{'name': 'Audio', 'selector': '.audio', 'format': 'audio', 'limit': 5,
                            'audio': {'attribute': 'onclick', 'steps': [
                                {'op': 'call_argument', 'function': 'playSound'},
                                {'op': 'replace', 'old': '_', 'new': '-'},
                                {'op': 'prefix', 'value': 'audio/'}, {'op': 'suffix', 'value': '.mp3'}]}}],
                'unavailable': []}

    def test_shared_javascript_deduplicates_mdd_local_inline_and_module_imports(self):
        assets = self.host.load('service.dictionary_assets')
        path = Path(self.temp.name) / 'sample.mdx'
        (path.parent / 'local.js').write_text('const local=1;', encoding='utf-8')
        values = {'\\js\\main.js': b'import "./audio.js";',
                  '\\js\\audio.js': b'function playSound(id){return "audio/"+id.replaceAll("_","-")+".mp3";}'}
        self.builder.mdd_lookup = lambda key, **kwargs: [values[key]] if key in values else []
        html = ('<script src="js/main.js"></script><script src="local.js"></script>'
                '<script>const shared=1;</script><script src="https://example.org/remote.js"></script>'
                '<script src="missing.js"></script><script src="../outside.js"></script>')
        samples = [{'word': word, 'html': html} for word in ('apple', 'book', 'run')]
        result = assets.collect_javascript(samples, self.builder, str(path))
        by_source = {item['source']: item for item in result}
        self.assertEqual(len(result), 7)
        self.assertIn('playSound', by_source['js/audio.js']['content'])
        self.assertEqual(by_source['local.js']['content'], 'const local=1;')
        self.assertEqual(by_source['missing.js']['status'], 'missing')
        self.assertEqual(by_source['https://example.org/remote.js']['status'], 'excluded_external_or_invalid')
        sent = json.loads(self.engine.build_prompt(samples, ['Audio'], result))
        self.assertEqual(len(sent['samples']), 3)
        self.assertEqual(len(sent['dictionary_javascript']), 7)
        self.assertEqual(sum('playSound' in item.get('content', '') for item in sent['dictionary_javascript']), 1)

    def test_javascript_limits_cancel_and_resource_boundaries(self):
        assets = self.host.load('service.dictionary_assets')
        path = Path(self.temp.name) / 'sample.mdx'
        samples = [{'word': 'word', 'html': '<script src="large.js"></script>'}]
        self.builder.mdd_lookup = lambda *args, **kwargs: [b'x' * (assets.JS_FILE_LIMIT + 10)]
        result = assets.collect_javascript(samples, self.builder, str(path))
        self.assertTrue(result[0]['truncated'])
        self.assertEqual(len(result[0]['content']), assets.JS_FILE_LIMIT)
        with self.assertRaises(ValueError):
            assets.collect_javascript(samples, self.builder, str(path), cancelled=lambda: True)
        for key in ('../private.js', '%2e%2e/private.js', 'C:/private.js', 'https://example.org/a.js'):
            with self.assertRaises(ValueError):
                assets.read_asset(self.builder, str(path), key)

    def test_audio_transformation_exports_identical_bytes_with_new_anki_reference(self):
        rules = self.engine.parse_rules(json.dumps(self.audio_rules()), ['Audio'])
        root = Path(self.temp.name)
        path = root / 'sample.mdx'
        (root / 'audio').mkdir()
        payload = b'original audio bytes'
        audio = root / 'audio' / 'apple-uk.mp3'
        audio.write_bytes(payload)
        html = '<a class="audio" onclick="playSound(\'apple_uk\')">UK</a><script src="audio.js"></script>'
        self.builder.mdx_lookup = lambda *args, **kwargs: [html]
        samples = [{'word': 'apple', 'html': html}]
        preview = self.engine.validate_samples(samples, rules, self.builder, str(path))
        self.assertEqual(preview[0]['fields']['Audio'], '<a href="sound:audio/apple-uk.mp3">UK</a>')
        media_module = self.host.load('service.mdx_media')
        class Service(media_module.MdxMediaMixin):
            pass
        service = Service()
        service.dict_path, service.builder = str(path), self.builder
        service.media_path = lambda name: str(root / 'media' / name)
        service._is_fuzzy_enabled = lambda: False
        self.host.host.config.export_media = True
        service.title = 'Sample'
        service.missed_css = set()
        extracted = self.engine.extract_required(html, rules['fields'][0], self.builder, str(path))
        result = self.engine.adapt_extracted(service, extracted, rules['fields'][0])
        name = service.media_name('audio/apple-uk.mp3')
        self.assertEqual(result, '[sound:' + name + ']UK')
        self.assertEqual((root / 'media' / name).read_bytes(), payload)
        self.assertEqual(audio.read_bytes(), payload)
        self.assertNotIn('onclick', result)
        self.assertNotIn('<script', result)
        with patch.object(service, 'save_media_files', return_value=['audio/apple-uk.mp3']):
            with self.assertRaises(ValueError):
                self.engine.adapt_extracted(service, extracted, rules['fields'][0])
        audio.unlink()
        with self.assertRaises(ValueError):
            self.engine.extract_required(html, rules['fields'][0], self.builder, str(path))

    def test_audio_rules_reject_code_unknown_steps_missing_map_keys_and_remote_paths(self):
        rules = self.audio_rules()
        for step in ({'op': 'eval', 'value': 'code'}, {'op': 'replace', 'old': '', 'new': 'x'},
                     {'op': 'call_argument', 'function': 'bad()'}, {'op': 'map', 'values': {'x': 7}}):
            rules['fields'][0]['audio']['steps'] = [step]
            with self.assertRaises(ValueError):
                self.engine.parse_rules(json.dumps(rules), ['Audio'])
        rule = self.audio_rules()['fields'][0]
        for html in ('<a class="audio" onclick="playSound(foo())">Play</a>',
                     '<a class="audio" onclick="playSound(\'../../private\')">Play</a>'):
            with self.assertRaises(ValueError):
                self.engine.extract_required(html, rule)
        rule['audio'] = {'attribute': 'data-id', 'steps': [{'op': 'map', 'values': {'known': 'audio/a.mp3'}}]}
        with self.assertRaises(ValueError):
            self.engine.extract_required('<a class="audio" data-id="unknown">Play</a>', rule)
        rule['audio'] = {'attribute': 'href', 'steps': []}
        with self.assertRaises(ValueError):
            self.engine.extract_required('<a class="audio" href="https://example.org/a.mp3">Play</a>', rule)

    def test_stable_adapter_identity_and_original_method_update_preserve_other_code(self):
        updates = self.host.load('service.script_updates')
        filename, source = self.engine.render_script(str(Path(self.temp.name) / 'sample.mdx'), self.rules)
        self.assertEqual(self.engine.render_script(str(Path(self.temp.name) / 'sample.mdx'), self.rules), (filename, source))
        original = ('from ..base import MdxService, register, export\n\n'
                    'KEEP = "original constant"\n'
                    '@register(["Existing", "Existing"])\nclass Original(MdxService):\n'
                    '    def helper(self):\n        return KEEP\n'
                    '    @export(["Meaning", "Meaning"])\n'
                    '    def old_meaning(self):\n        return "old result"\n'
                    '    @export("Untouched")\n'
                    '    def untouched(self):\n        return "stay"\n')
        updated = updates.update_source(original, self.rules, 'Original')
        self.assertIn('class Original(MdxService)', updated)
        self.assertIn('return KEEP', updated)
        self.assertIn('return "stay"', updated)
        self.assertNotIn('return "old result"', updated)
        self.assertIn('def old_meaning(self)', updated)
        self.assertIn("@export(['Phonetic', 'Phonetic'])", updated)
        self.assertEqual(updated.count('@export(["Meaning", "Meaning"])'), 1)
        twice = updates.update_source(updated, self.rules, 'Original')
        self.assertEqual(twice.count('def old_meaning(self)'), 1)
        self.assertEqual(twice.count("@export(['Phonetic', 'Phonetic'])"), 1)
        ast.parse(twice)
        compact = original.replace('def old_meaning(self):\n        return "old result"', 'def old_meaning(self): return "old result"')
        ast.parse(updates.update_source(compact, self.rules, 'Original'))

    def test_repeated_clock_tick_never_overwrites_a_script_backup(self):
        updates = self.host.load('service.script_updates')
        root = Path(self.temp.name)
        path = root / 'adapter.py'
        old, new = 'value = "old"\n', 'value = "new"\n'
        path.write_text(old, encoding='utf-8')
        instant = datetime.now(timezone.utc)
        with patch.object(updates, 'datetime', types.SimpleNamespace(now=lambda zone: instant)):
            updates.replace_script(path, new, old, root)
            backup = next(updates.trash_directory(root).glob('script_*.bak'))
            updates.restore_script(backup, root)
            self.assertEqual(path.read_text(), old)
            self.assertEqual(backup.read_text(), old)
            recycled = updates.recycle_script(path, root)
            updates.restore_script(recycled, root)
        self.assertEqual(path.read_text(), old)
        backups = list(updates.trash_directory(root).glob('script_*.bak'))
        self.assertEqual(len(backups), 3)
        self.assertEqual({backup.read_text() for backup in backups}, {old, new})

    def test_update_backup_recovery_conflict_and_seven_day_expiry(self):
        updates = self.host.load('service.script_updates')
        root = Path(self.temp.name)
        path = root / 'adapter.py'
        old, new = 'value = "old"\n', 'value = "new"\n'
        path.write_text(old, encoding='utf-8')
        cache = Path(py_compile.compile(str(path), doraise=True))
        self.assertTrue(cache.exists())
        updates.replace_script(path, new, old, root)
        self.assertFalse(cache.exists())
        self.assertEqual(path.read_text(), new)
        backups = list(updates.trash_directory(root).glob('script_*.bak'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_text(), old)
        with self.assertRaises(ValueError):
            updates.replace_script(path, old, old, root)
        updates.restore_script(backups[0], root)
        self.assertEqual(path.read_text(), old)
        recycled = updates.recycle_script(path, root)
        self.assertFalse(path.exists())
        updates.restore_script(recycled, root)
        self.assertEqual(path.read_text(), old)
        now = datetime.now(timezone.utc)
        def archived(days):
            stamp = (now - timedelta(days=days)).astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')
            result = updates.trash_directory(root) / ('script_' + stamp + '_other.py.bak')
            result.write_text('old archive', encoding='utf-8')
            return result
        expired, boundary = archived(8), archived(7)
        active_old = root / 'active_old.py'
        active_old.write_text('active = True', encoding='utf-8')
        unknown = updates.trash_directory(root) / 'unknown.py.bak'
        unknown.write_text('keep', encoding='utf-8')
        self.assertEqual(updates.prune_old_scripts(root, now), 1)
        self.assertFalse(expired.exists())
        self.assertTrue(boundary.exists())
        self.assertTrue(unknown.exists())
        self.assertTrue(active_old.exists())
        self.assertEqual(path.read_text(), old)

    def test_attachment_toggles_send_only_selected_data_and_reference_original_script(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        root = Path(self.temp.name)
        filename, source = self.engine.render_script(str(root / 'sample.mdx'), self.rules)
        original_path = root / filename
        original_path.write_text(source, encoding='utf-8')
        fake = types.SimpleNamespace(support=True, builder=self.builder)
        selected = {'html': False, 'js': False, 'script': True}
        with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text', return_value=json.dumps(self.rules)) as request:
            result = module.Generation(str(root / 'sample.mdx'), 'ai:test', [], None, 'Update meaning', selected,
                                       [str(original_path), str(original_path)]).load_services()
        self.assertNotIn('error', result)
        sent = json.loads(request.call_args.args[1])
        self.assertNotIn('html', sent['samples'][0])
        self.assertEqual(sent['dictionary_javascript'], [])
        self.assertEqual(len(sent['original_scripts']), 1)
        self.assertEqual(sent['original_scripts'][0]['source'], source)
        self.assertEqual(result['filename'], filename)
        self.assertEqual(result['original']['path'], str(original_path.resolve()))
        record_path = self.host.load('service.script_updates').write_conversation(result['record'], root)
        self.assertEqual(json.loads(Path(record_path).read_text(encoding='utf-8'))['response'], json.dumps(self.rules))
        with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text') as request:
            missing = module.Generation(str(root / 'sample.mdx'), 'ai:test', [], None, 'Update', selected, ['missing.py']).load_services()
            request.assert_not_called()
        self.assertIn('error', missing)

    def test_existing_python_encoding_is_preserved_on_update_and_restore(self):
        updates = self.host.load('service.script_updates')
        root = Path(self.temp.name)
        path = root / 'legacy.py'
        old = '# coding: gbk\nvalue = "旧内容"\n'
        new = '# coding: gbk\nvalue = "新内容"\n'
        path.write_bytes(old.encode('gbk'))
        self.assertEqual(updates.original_scripts([str(path)])[0]['source'], old)
        updates.replace_script(path, new, old, root)
        self.assertEqual(path.read_bytes().decode('gbk').splitlines(), new.splitlines())
        backup = next(updates.trash_directory(root).glob('script_*.bak'))
        updates.restore_script(backup, root)
        self.assertEqual(path.read_bytes(), old.encode('gbk'))

    def test_manager_merges_variants_and_disables_missing_local_file_actions(self):
        root = Path(self.temp.name)
        dictionary = root / 'sample.mdx'
        dictionary.touch()
        script = root / 'adapter.py'
        script.write_text('value = 1', encoding='utf-8')
        raw = types.SimpleNamespace(__unique__='raw', __title__='Default', __dict_path__=str(dictionary), __path__='')
        custom = types.SimpleNamespace(__unique__='Custom', __title__='Sample AI oldhash', __dict_path__=str(dictionary), __path__=str(script))
        missing = types.SimpleNamespace(__unique__='Missing', __title__='Missing', __dict_path__=str(root / 'missing.mdx'), __path__=str(script))
        registry = sys.modules[support.PACKAGE + '.service'].service_manager
        registry.local_services = [raw, custom, missing]
        registry.local_custom_services = [custom, missing]
        self.host.host.config.dicts = {'Custom': {'enabled': True}, 'legacy': {'enabled': True}}
        dialog = self.host.load('gui.dictmanager').DictManageDialog(None)
        self.host.widgets.append(dialog)
        self.assertEqual(len(dialog._options), 3)
        row, absent, legacy = dialog._options
        self.assertEqual(legacy['unique'], 'legacy')
        self.assertTrue(legacy['check_btn'].font().strikeOut())
        with patch.object(self.host.qt.QMessageBox, 'question', return_value=self.host.qt.QMessageBox.StandardButton.No):
            dialog.delete_dictionary(legacy)
        self.assertIn(legacy, dialog._options)
        with patch.object(self.host.qt.QMessageBox, 'question', return_value=self.host.qt.QMessageBox.StandardButton.Yes) as confirm, \
                patch.object(self.host.load('service.script_library'), 'exclude_scripts'), \
                patch.object(self.host.load('service.script_library'), 'publish'), \
                patch.object(dialog, 'detect_directories'):
            dialog.delete_dictionary(legacy)
        self.assertNotIn(legacy, dialog._options)
        self.assertEqual(confirm.call_args.args[-1], self.host.qt.QMessageBox.StandardButton.No)
        self.assertEqual(set(row['uniques']), {'raw', 'Custom'})
        self.assertNotIn('oldhash', row['check_btn'].text())
        self.assertTrue(row['generate_btn'].isEnabled())
        self.assertTrue(row['edit_btn'].isEnabled())
        self.assertFalse(absent['generate_btn'].isEnabled())
        self.assertFalse(absent['generate_btn'].isHidden())
        self.assertTrue(absent['missing_label'].isHidden())
        row['check_btn'].setChecked(False)
        dialog.save()
        saved = self.host.host.config.update.call_args.args[0]['dicts']
        self.assertFalse(saved['raw']['enabled'])
        self.assertFalse(saved['Custom']['enabled'])
        self.assertNotIn('legacy', saved)

    def test_missing_key_or_invalid_model_fails_before_dictionary_initialization(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        settings = self.host.load('service.ai_config')
        settings._session_keys['test'] = ''
        with patch.object(base, 'MdxService') as service:
            result = module.Generation('sample.mdx', 'ai:test', [], None, 'Extract').load_services()
            service.assert_not_called()
        self.assertIn('Key', result['error'])
        settings._session_keys['test'] = 'test-session-key'
        self.host.host.config.ai_profiles[0].update(parameters='{invalid json')
        with patch.object(base, 'MdxService') as service:
            result = module.Generation('sample.mdx', 'ai:test', [], None, 'Extract').load_services()
            service.assert_not_called()
        self.assertIn('JSON', result['error'])

    def test_invalid_inputs_preserve_preview_and_restore_is_blocked_during_generation(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        dialog.result = {'existing': True}
        dialog.preview.setPlainText('Previous preview')
        dialog.save_button.setEnabled(True)
        for checkbox in dialog.attachments.values():
            checkbox.setChecked(False)
        dialog.begin()
        self.assertEqual(dialog.preview.toPlainText(), 'Previous preview')
        self.assertEqual(dialog.result, {'existing': True})
        self.assertTrue(dialog.save_button.isEnabled())
        dialog.loader = Mock()
        with patch.object(module.QFileDialog, 'getOpenFileName') as picker:
            dialog.restore_old_script()
            picker.assert_not_called()
        dialog.loader = None

    def test_conversation_keeps_failed_response_and_reports_record_save_errors(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        record = {'request': {'user_command': 'Extract meaning'}, 'response': 'invalid JSON'}
        with patch.object(module, 'write_conversation', side_effect=OSError):
            dialog.ready({'error': 'Bad rules', 'record': record})
            dialog.ready({'error': 'Second failure', 'record': dict(record, response='second reply')})
        self.assertIn('Second failure', dialog.status.text())
        self.assertIn('Second failure', dialog.status.text())
        self.assertEqual(len(dialog.conversations), 2)
        self.assertIn('invalid JSON', dialog.conversation.toPlainText())
        self.assertIn('second reply', dialog.conversation.toPlainText())
        self.assertIn('Extract meaning', dialog.samples_view.toPlainText())

    def debug_candidate(self, rules=None):
        base = self.host.load('service.base')
        service = base.MdxService('missing.mdx')
        service.dict_path = str(Path(self.temp.name) / 'sample.mdx')
        Path(service.dict_path).touch()
        service.builder = self.builder
        service.media_dir = str(Path(self.temp.name) / 'real-media')
        rules = rules or self.rules
        filename, source = self.engine.render_script(service.dict_path, rules)
        return service, {'samples': self.engine.collect_samples(self.builder), 'rules': rules,
                         'filename': filename, 'source': source, 'original': None}

    def test_debug_executes_generated_exports_without_touching_actual_media(self):
        service, result = self.debug_candidate()
        actual_media = Path(service.media_dir)
        actual_media.mkdir()
        sentinel = actual_media / 'keep.mp3'
        sentinel.write_bytes(b'unchanged')
        report = self.host.load('service.script_debug').debug_exports(service, result)
        self.assertTrue(report['passed'], report)
        self.assertEqual(len(report['rows']), 6)
        self.assertIn('Meaning of word0', report['rows'][0]['result'])
        self.assertEqual(list(actual_media.iterdir()), [sentinel])
        self.assertEqual(sentinel.read_bytes(), b'unchanged')

    def test_debug_reports_each_word_field_traceback_and_rejects_modified_method_body(self):
        service, result = self.debug_candidate()
        original = self.builder.mdx_lookup
        self.builder.mdx_lookup = lambda word, **kwargs: ['<span class="def">definition only</span>'] if word == 'word12' else original(word)
        report = self.host.load('service.script_debug').debug_exports(service, result)
        self.assertFalse(report['passed'])
        failure = next(row for row in report['rows'] if not row['passed'])
        self.assertEqual((failure['word'], failure['field']), ('word12', 'Phonetic'))
        self.assertIn('extract_required', failure['traceback'])
        result['source'] = result['source'].replace('return adapt_extracted(self, value, RULES[0])', 'return __import__("os").getcwd()')
        rejected = self.host.load('service.script_debug').debug_exports(service, result)
        self.assertIn('validated generated template', rejected['rows'][0]['error'])

    def test_debug_skips_legacy_module_and_constructor_code(self):
        service, result = self.debug_candidate()
        original = '''raise RuntimeError('module must not execute')
@register(['Old', 'Old'])
class Old(MdxService):
    def __init__(self):
        raise RuntimeError('constructor must not execute')
    @export(['Meaning', 'Meaning'])
    def meaning(self):
        return 'old'
'''
        result['original'] = {'source': original, 'path': str(Path(self.temp.name) / 'old.py')}
        result['source'] = self.host.load('service.script_updates').update_source(original, self.rules)
        report = self.host.load('service.script_debug').debug_exports(service, result)
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['original_initialization'], 'not_executed')

    def test_chat_record_matches_actual_payload_and_failed_reply_is_preserved(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        fake = types.SimpleNamespace(support=True, builder=self.builder)
        history = [{'role': 'user', 'content': 'previous message'}, {'role': 'assistant', 'content': 'previous reply'}]
        prepared = []
        operation = module.Generation('sample.mdx', 'ai:test', [], self.names, 'Extract',
                                      history=history, message='Fix the audio')
        operation.on_prepared = prepared.append
        with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text', return_value='{invalid json') as request:
            result = operation.load_services()
        self.assertIn('error', result)
        self.assertEqual(result['record']['response'], '{invalid json')
        self.assertIn('traceback', result['record']['local'])
        self.assertEqual(request.call_args.kwargs['history'], history)
        self.assertEqual(prepared[0]['state'], 'sending')
        payload = module.request_payload(operation.connection.profile, request.call_args.args[1], request.call_args.args[2], history=history)
        self.assertEqual(result['record']['payload'], payload)
        self.assertNotIn('test-session-key', json.dumps(result['record']))

    def test_chat_plain_answer_keeps_current_script_and_copy_contains_complete_record(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        fake = types.SimpleNamespace(support=True, builder=self.builder)
        with patch.object(base, 'MdxService', return_value=fake), patch.object(module, 'request_ai_text', return_value='This selector extracts the definition.'):
            result = module.Generation('sample.mdx', 'ai:test', [], None, 'Extract', message='Explain the selector').load_services()
        self.assertTrue(result['chat_only'])
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        dialog.script_directory = self.temp.name
        dialog.result = {'source': 'previous valid script'}
        dialog.ready(result)
        self.assertEqual(dialog.result['source'], 'previous valid script')
        dialog.copy_information(all_records=True)
        copied = self.host.app.clipboard().text()
        self.assertIn('Explain the selector', copied)
        self.assertIn('This selector extracts the definition.', copied)
        self.assertNotIn('test-session-key', copied)

    def test_automatic_debug_runs_once_without_another_ai_request(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        service, _ = self.debug_candidate()
        with patch.object(base, 'MdxService', return_value=service), patch.object(module, 'request_ai_text', return_value=json.dumps(self.rules)) as request:
            result = module.Generation(service.dict_path, 'ai:test', [], self.names, 'Extract', debug=True).load_services()
        request.assert_called_once()
        self.assertTrue(result['debug_record']['passed'], result)
        self.assertEqual(len(result['debug_record']['rows']), 6)

    def test_debug_exports_audio_into_temporary_media_and_preserves_bytes(self):
        from hashlib import sha256
        service, result = self.debug_candidate(self.audio_rules())
        self.builder.mdx_lookup = lambda word, **kwargs: ['<b>%s</b><a class="audio" onclick="playSound(\'apple_uk\')">play</a>' % word]
        audio = Path(service.dict_path).parent / 'audio' / 'apple-uk.mp3'
        audio.parent.mkdir()
        audio.write_bytes(b'original pronunciation bytes')
        result['samples'] = self.engine.collect_samples(self.builder)
        report = self.host.load('service.script_debug').debug_exports(service, result)
        self.assertTrue(report['passed'], report)
        self.assertEqual(len(report['files']), 1)
        self.assertEqual(report['files'][0]['sha256'], sha256(audio.read_bytes()).hexdigest())
        self.assertTrue(all('[sound:' in row['result'] for row in report['rows']))
        self.assertFalse(Path(service.media_dir).exists())

    def test_cancelled_response_is_saved_without_applying_candidate(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        service, _ = self.debug_candidate()
        cancelled = [False]
        def reply(*args, **kwargs):
            cancelled[0] = True
            return json.dumps(self.rules)
        with patch.object(base, 'MdxService', return_value=service), patch.object(module, 'request_ai_text', side_effect=reply):
            result = module.Generation(service.dict_path, 'ai:test', [], self.names, 'Extract',
                                       record_directory=self.temp.name).load_services(cancelled=lambda: cancelled[0])
        self.assertNotIn('source', result)
        self.assertEqual(result['record']['state'], 'cancelled')
        self.assertTrue(result['record']['response'])
        records = self.host.load('service.script_information').load_history(self.temp.name, module.dictionary_identity(service.dict_path))
        self.assertEqual(records, [])
        self.assertEqual(result['record']['state'], 'cancelled')

    def test_cancelling_updates_visible_request_and_missing_dictionary_debug_keeps_record_id(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'missing.mdx')
        self.host.widgets.append(dialog)
        dialog.script_directory = self.temp.name
        dialog.add_information({'id': 'pending-request', 'kind': 'request', 'state': 'sending', 'request': {}})
        dialog.loader = Mock()
        dialog.cancel_operation()
        dialog.loader.stop.assert_called_once()
        dialog.loader = None
        self.assertEqual(dialog.conversations[0]['state'], 'cancelled')
        with patch.object(self.host.load('service.base'), 'MdxService', return_value=types.SimpleNamespace(support=False)):
            result = module.DebugOperation('missing.mdx', {'source': ''}, record_directory=self.temp.name).load_services()
        record = result['debug_record']
        self.assertTrue(record['id'])
        self.assertTrue(record['time'])
        dialog.ready(result)
        dialog.ready({'history_records': module.load_history(self.temp.name, module.dictionary_identity('missing.mdx'))})
        self.assertEqual(sum(value['id'] == record['id'] for value in dialog.conversations), 1)

    def test_automatic_debug_records_invalid_extraction_without_another_request(self):
        module = self.host.load('gui.script_generator')
        base = self.host.load('service.base')
        service, _ = self.debug_candidate()
        rules = dict(self.rules, fields=[dict(self.rules['fields'][0], selector='.missing')])
        with patch.object(base, 'MdxService', return_value=service), patch.object(module, 'request_ai_text', return_value=json.dumps(rules)) as request:
            result = module.Generation(service.dict_path, 'ai:test', [], None, 'Extract', debug=True).load_services()
        request.assert_called_once()
        self.assertIn('error', result)
        self.assertFalse(result['debug_record']['passed'])
        self.assertIn('traceback', result['debug_record']['rows'][0])


    def test_each_window_has_new_session_and_import_keeps_original_records(self):
        module = self.host.load('gui.script_generator')
        first = module.ScriptGeneratorDialog(None, 'sample.mdx')
        second = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.extend([first, second])
        first.script_directory = second.script_directory = self.temp.name
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertEqual(second.conversations, [])
        original = {'id': 'old-request', 'session_id': first.session_id,
                    'dictionary_id': module.dictionary_identity('sample.mdx'), 'kind': 'request',
                    'request': {}, 'user_message': 'original question', 'response': 'complete reply', 'state': 'completed'}
        first.add_information(original)
        second.ready({'history_records': [original, dict(original, id='foreign', dictionary_id='other')],
                      'import_session': first.session_id})
        self.assertEqual(len(second.conversations), 1)
        imported = second.conversations[0]
        self.assertEqual(imported['session_id'], second.session_id)
        self.assertNotEqual(imported['id'], original['id'])
        self.assertEqual(imported['imported_from']['record_id'], original['id'])
        self.assertEqual(module.compact_history(second.conversations)[1]['content'], 'complete reply')
        self.assertIsNone(second.result)
        old = module.load_history(self.temp.name, original['dictionary_id'], session_id=first.session_id)
        self.assertEqual(old, [])
        self.assertTrue(first.conversations)

    def test_conversation_is_a_single_ordered_escaped_role_transcript(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        dialog.script_directory = self.temp.name
        dialog.add_information({'id': 'one', 'kind': 'request', 'state': 'sending', 'user_message': 'first message',
                                'instructions': 'parse', 'request': {'html': '<script>alert(1)</script>', 'js': 'audio/path.js'}})
        self.assertIn('正在等待 AI', dialog.conversation.toPlainText())
        dialog.add_information({'id': 'one', 'kind': 'request', 'state': 'completed', 'user_message': 'first message',
                                'instructions': 'parse', 'request': {'html': '<script>alert(1)</script>', 'js': 'audio/path.js'},
                                'response': 'first answer'})
        dialog.add_information({'kind': 'debug', 'passed': False, 'error': 'missing pronunciation'})
        dialog.add_information({'kind': 'request', 'state': 'completed', 'user_message': 'second message',
                                'request': {}, 'response': 'second answer'})
        for i in range(len(dialog.conversations)):
            dialog._expanded_messages.update('%s-%s' % (i, role) for role in ('user', 'assistant', 'local', 'debug'))
        dialog.render_conversation()
        plain = dialog.conversation.toPlainText()
        expected = ['first message', 'first answer', 'missing pronunciation', 'second message', 'second answer']
        self.assertEqual([plain.index(text) for text in expected], sorted(plain.index(text) for text in expected))
        self.assertEqual(plain.count('first message'), 1)
        self.assertIn('<script>alert(1)</script>', plain)
        self.assertIn('audio/path.js', plain)
        self.assertNotIn('正在等待 AI', plain)
        self.assertFalse(dialog.conversation.openLinks())
        self.assertFalse(hasattr(dialog, 'history_tree'))
        cursor = dialog.conversation.textCursor()
        cursor.select(module.QTextCursor.SelectionType.Document)
        dialog.conversation.setTextCursor(cursor)
        dialog.copy_selected_information()
        self.assertIn('first message', self.host.app.clipboard().text())
        self.assertIn('second answer', self.host.app.clipboard().text())

    def test_messages_fold_to_five_lines_without_losing_full_text(self):
        module = self.host.load('gui.script_generator')
        dialog = module.ScriptGeneratorDialog(None, 'sample.mdx')
        self.host.widgets.append(dialog)
        dialog.script_directory = self.temp.name
        content = '\n'.join('line%s' % i for i in range(9))
        preview, folded = dialog.message_preview(content)
        self.assertTrue(folded)
        self.assertEqual(len(preview.splitlines()), 5)
        self.assertNotIn('line8', preview)
        self.assertEqual(dialog.message_preview('one\ntwo'), ('one\ntwo', False))
        dialog.add_information({'kind': 'request', 'request': {}, 'user_message': 'question', 'response': content})
        self.assertNotIn('line8', dialog.conversation.toPlainText())
        dialog.toggle_message(module.QUrl('toggle:0-assistant'))
        self.assertIn('line8', dialog.conversation.toPlainText())
        dialog.toggle_message(module.QUrl('toggle:0-assistant'))
        self.assertNotIn('line8', dialog.conversation.toPlainText())
        dialog.copy_information(all_records=True)
        self.assertIn('line8', self.host.app.clipboard().text())
        self.assertEqual(module.compact_history(dialog.conversations)[1]['content'], content)
        wrapped, folded = dialog.message_preview('emoji 😀 ' * 1000)
        self.assertTrue(folded)
        self.assertLess(len(wrapped), 8000)
        self.assertNotIn('\ufffd', wrapped)
