"""Combined requests: protocol, grouping, validation, cancellation and rollback."""

import json
import sys
import threading
import types
import unittest
from copy import deepcopy
from unittest.mock import Mock, patch

import test_ai
import test_modularization as support


class CombinedAITests(unittest.TestCase):
    def setUp(self):
        self.host = test_ai.AITests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.load = self.host.load
        self.common = self.host.query_module()
        qt = sys.modules['aqt.qt']
        qt.QApplication = types.SimpleNamespace(processEvents=Mock())
        qt.QMessageBox = types.SimpleNamespace(warning=Mock())
        progress_module = types.ModuleType(support.PACKAGE + '.gui.ai_progress')
        self.progress = Mock()
        self.progress.abort.return_value = False
        progress_module.AIProgressWindow = Mock(return_value=self.progress)
        sys.modules[progress_module.__name__] = progress_module
        self.runner_module = self.load('query.ai_runner')
        self.ai = self.load('service.ai')
        self.batching = self.load('service.ai_support.batching')
        self.settings = self.host.settings
        self.profile = self.host.profile
        self.unique = self.host.unique
        self.profile['send_mode'] = 'note'
        self.host.host.config.ai_send_mode = 'note'
        self.model = {'id': 1, 'flds': [{'name': name} for name in ('Word', 'Meaning', 'Similar', 'Dictionary')]}
        self.maps = [
            {'fld_name': 'Word', 'word_checked': True},
            {'fld_ord': 1, 'dict_unique': self.unique, 'ai_prompt': 'Explain {{Word}}', 'ignore': False},
            {'fld_ord': 2, 'dict_unique': self.unique, 'ai_prompt': 'Compare {{Word}} in a table', 'ignore': False},
            {'fld_ord': 3, 'dict_unique': 'local', 'ignore': False},
        ]

    def note(self, word='apple'):
        return {'Word': word, 'Meaning': 'original meaning', 'Similar': 'original similar', 'Dictionary': 'original dictionary'}

    def runner(self, notes=None, **kwargs):
        return self.runner_module.AIQueryRunner(notes or [self.note()], mappings=self.maps, model=self.model, **kwargs)

    def response(self, text, mode='responses'):
        data = ({'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
                if mode == 'responses' else
                {'choices': [{'finish_reason': 'stop', 'message': {'content': text}}]})
        return Mock(status_code=200, json=Mock(return_value=data))

    def test_send_mode_persists_and_legacy_profiles_stay_per_field(self):
        self.assertEqual(self.settings.new_profile()['send_mode'], 'field')
        self.settings.save_profiles([self.profile], {self.profile['id']: 'key'})
        self.settings.clear_session_keys()
        self.assertEqual(self.settings.profiles()[0]['send_mode'], 'note')
        legacy = dict(self.profile)
        legacy.pop('send_mode')
        store = self.load('service.ai_store')
        store.write_settings({'profiles': [legacy], 'keys': {}})
        self.assertEqual(self.settings.profiles()[0]['send_mode'], 'field')
        self.settings.save_profiles([legacy], {})
        self.assertEqual(store.read_settings()['profiles'][0]['send_mode'], 'field')
        invalid = dict(self.profile, send_mode='all-notes')
        with self.assertRaises(ValueError):
            self.settings.save_profiles([invalid], {})
        self.assertEqual(store.read_settings()['profiles'][0]['send_mode'], 'field')

    def test_combined_protocols_make_one_request_and_render_each_table(self):
        table = '| Word | Relation |\n| --- | --- |\n| pear | fruit |'
        text = json.dumps({'Meaning': '**apple** means a fruit.', 'Similar': table})
        self.profile['skill'] = 'Explain concisely.'
        templates = {task['fld_name'] if 'fld_name' in task else self.model['flds'][task['fld_ord']]['name']:
                     task['ai_prompt'] for task in self.maps[1:3]}
        # HTML parsing is covered with real BeautifulSoup in service runtime tests.
        with patch.object(self.ai, 'render_prompt', side_effect=lambda template, fields: template.replace('{{Word}}', fields['Word'])):
            for mode in ('responses', 'chat'):
                with self.subTest(mode=mode):
                    self.profile['mode'] = mode
                    with patch.object(self.ai, '_send', return_value=self.response(text, mode)) as send:
                        result = self.ai.query_ai_many(self.unique, templates, {'Word': 'apple'})
                    send.assert_called_once()
                    payload = send.call_args.args[2]
                    instructions = payload.get('instructions') if mode == 'responses' else payload['messages'][0]['content']
                    prompt = payload.get('input') if mode == 'responses' else payload['messages'][-1]['content']
                    self.assertIn(self.profile['skill'], instructions)
                    self.assertIn(self.batching.OUTPUT_INSTRUCTIONS, instructions)
                    self.assertEqual(json.loads(prompt)['tasks']['Meaning'], 'Explain apple')
                    self.assertIn('<strong>apple</strong>', result['Meaning'].result)
                    self.assertIn('<table>', result['Similar'].result)
                    self.assertIn('<td>pear</td>', result['Similar'].result)
                    self.assertNotIn('Similar', result['Meaning'].result)

    def test_json_validation_rejects_partial_ambiguous_or_empty_answers(self):
        valid = '{"Meaning":"fruit","Similar":"pear"}'
        self.assertEqual(self.batching.parse_fields('```json\n' + valid + '\n```', ['Meaning', 'Similar']),
                         {'Meaning': 'fruit', 'Similar': 'pear'})
        for text in ('not JSON', '{"Meaning":"fruit"}',
                     '{"Meaning":"fruit","Similar":"pear","Other":"unexpected"}',
                     '{"Meaning":"first","Meaning":"second","Similar":"pear"}',
                     '{"Meaning":null,"Similar":"pear"}', '{"Meaning":" ","Similar":"pear"}',
                     '{"Meaning":["fruit"],"Similar":"pear"}', '["fruit","pear"]',
                     'Commentary\n' + valid, valid[:-1]):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.batching.parse_fields(text, ['Meaning', 'Similar'])
        with patch.object(self.ai, 'render_prompt', return_value='hello'), \
                patch.object(self.ai, '_send', return_value=self.response('{"Meaning":"fruit"}')):
            with self.assertRaises(self.ai.AIError) as error:
                self.ai.query_ai_many(self.unique, {'Meaning': 'first', 'Similar': 'second'}, {})
        self.assertEqual(error.exception.code, 'structured_output')

    def test_prompt_expansion_never_reinterprets_inserted_values_or_field_names(self):
        renderer = Mock(side_effect=lambda template, fields: template.replace('{{Word}}', fields['Word']))
        prompt = self.batching.build_prompt({'{{Output}}': 'Explain {{Word}}', 'Similar': 'Compare {{Word}}'},
                                          {'Word': '{{Other}}'}, renderer)
        self.assertEqual(json.loads(prompt)['tasks']['{{Output}}'], 'Explain {{Other}}')
        self.assertEqual(renderer.call_count, 2)

    def test_grouping_separates_notes_and_profiles_and_keeps_default(self):
        notes = [self.note(), self.note('pear')]
        runner = self.runner(notes)
        self.assertEqual(len(runner.tasks), 4)
        self.assertEqual([len(request.tasks) for request in runner.requests], [2, 2])
        self.assertEqual(runner.total_requests, 2)
        other = self.settings.new_profile('openai')
        other.update(model='test', send_mode='note')
        self.host.host.config.ai_profiles.append(other)
        self.maps[2]['dict_unique'] = 'ai:' + other['id']
        self.assertEqual(len(self.runner(notes).requests), 4)
        self.profile['send_mode'] = 'field'
        self.host.host.config.ai_send_mode = 'field'
        self.maps[2]['dict_unique'] = self.unique
        self.assertTrue(all(not request.merged for request in self.runner(notes).requests))

    def test_skip_ignore_and_current_field_filter_run_before_grouping(self):
        self.maps[1]['skip_valued'] = True
        runner = self.runner()
        self.assertEqual([task[1] for task in runner.tasks], ['Similar'])
        self.assertTrue(runner.requests[0].merged)
        self.assertEqual(self.runner(fields=[1]).requests, [])
        self.maps[1]['skip_valued'] = False
        self.assertEqual([task[1] for task in self.runner(fields=[1]).tasks], ['Meaning'])
        self.maps[2]['ignore'] = True
        self.assertEqual([task[1] for task in self.runner().tasks], ['Meaning'])

    def test_reference_validation_is_preserved_before_sending(self):
        self.maps[1]['ai_prompt'] = 'Read {{Similar}}'
        runner = self.runner()
        self.assertEqual(runner.failed, 1)
        self.assertEqual([task[1] for task in runner.tasks], ['Similar'])
        self.assertIn('Similar', runner.validation_errors[0])

    def test_combined_write_is_once_on_main_thread_using_original_inputs(self):
        note = self.note()
        main_thread = threading.get_ident()
        writes = []
        writer = lambda current: writes.append((threading.get_ident(), deepcopy(current)))
        runner = self.runner([note], writer=writer)
        note['Word'] = 'edited after starting'
        result = {'Meaning': self.ai.QueryResult(result='<p>fruit</p>'),
                  'Similar': self.ai.QueryResult(result='<table>pear</table>')}
        def query(unique, templates, values, **kwargs):
            self.assertEqual(values['Word'], 'apple')
            self.assertEqual(values['Meaning'], 'original meaning')
            self.assertEqual(set(templates), {'Meaning', 'Similar'})
            return result
        with patch.object(self.runner_module, 'query_ai_many', side_effect=query) as send, \
                patch.object(self.runner_module, 'query_ai') as single:
            runner.run(report=False)
        send.assert_called_once()
        single.assert_not_called()
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0], main_thread)
        self.assertEqual(writes[0][1]['Meaning'], '<p>fruit</p>')
        self.assertEqual(writes[0][1]['Similar'], '<table>pear</table>')
        self.assertEqual(note['Dictionary'], 'original dictionary')
        self.assertEqual(runner.updated_fields, 2)
        self.progress.update.assert_called_with(1, 0)

    def test_failure_restores_entire_group_and_does_not_send_fallback(self):
        note = self.note()
        original = dict(note)
        writer = Mock(side_effect=RuntimeError('write failed'))
        result = {'Meaning': self.ai.QueryResult(result='new meaning'),
                  'Similar': self.ai.QueryResult(result='new similar')}
        for error in (None, self.ai.AIError('invalid JSON', code='structured_output')):
            with self.subTest(error=error):
                runner = self.runner([note], writer=writer)
                with patch.object(self.runner_module, 'query_ai_many', return_value=result, side_effect=error) as send, \
                        patch.object(self.runner_module, 'query_ai') as single:
                    runner.run(report=False)
                self.assertEqual(note, original)
                self.assertEqual(runner.updated_fields, 0)
                self.assertEqual(runner.failed, 1)
                send.assert_called_once()
                single.assert_not_called()
                self.progress.update.assert_called_with(1, 1)

    def test_cancel_before_send_or_during_request_never_writes(self):
        note = self.note()
        original = dict(note)
        self.progress.abort.return_value = True
        runner = self.runner([note], writer=Mock())
        with patch.object(self.runner_module, 'query_ai_many') as send:
            runner.run(report=False)
        send.assert_not_called()
        self.assertTrue(runner.was_cancelled)
        self.progress.abort.return_value = False
        runner = self.runner([note], writer=Mock())
        def query(*args, **kwargs):
            self.progress.abort.return_value = True
            return {'Meaning': self.ai.QueryResult(result='changed'), 'Similar': self.ai.QueryResult(result='changed')}
        with patch.object(self.runner_module, 'query_ai_many', side_effect=query):
            runner.run(report=False)
        runner.writer.assert_not_called()
        self.assertEqual(note, original)
        self.assertTrue(runner.was_cancelled)


if __name__ == '__main__':
    unittest.main()
