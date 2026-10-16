"""AI profiles, request formats, prompt expansion, and safe Markdown output."""

import sys
import json
from pathlib import Path
import types
import unittest
from unittest.mock import Mock, patch

import test_modularization as support


class AITests(unittest.TestCase):
    def test_endpoint_selects_protocol_even_when_legacy_mode_disagrees(self):
        params = self.load('service.ai_support.parameters')
        for suffix, mode in [('responses', 'responses'), ('chat/completions', 'chat'),
                             ('interactions', 'interactions'), ('messages', 'messages')]:
            profile = dict(self.profile, base_url='https://example.test/v1/' + suffix, mode='outdated')
            self.assertEqual(params.protocol(profile), mode)
            profile['model'] = 'test'
            self.settings.validate_profile(profile)
        with self.assertRaises(ValueError):
            params.protocol(dict(self.profile, base_url='https://example.test/unknown'))

    def test_native_protocols_preserve_skill_history_and_extract_only_final_text(self):
        ai = self.load('service.ai')
        history = [{'role': 'user', 'content': 'first question'}, {'role': 'assistant', 'content': 'first answer'}]
        gemini = self.settings.new_profile('gemini')
        gemini.update(model='gemini-test', skill='shared instruction')
        payload = ai.request_payload(gemini, 'follow up', history=history)
        self.assertFalse(payload['store'])
        self.assertEqual(payload['system_instruction'], gemini['skill'])
        for text in ('first question', 'first answer', 'follow up'):
            self.assertIn(text, payload['input'])
        self.assertNotIn('reasoning', payload)
        reply = {'status': 'completed', 'steps': [
            {'type': 'thought', 'content': [{'type': 'text', 'text': 'private thought'}]},
            {'type': 'model_output', 'content': [{'type': 'text', 'text': 'answer'}]}]}
        self.assertEqual(ai.response_text(reply, 'interactions'), 'answer')
        reply['status'] = 'incomplete'
        with self.assertRaises(ai.AIError):
            ai.response_text(reply, 'interactions')
        claude = self.settings.new_profile('claude')
        claude.update(model='claude-test', skill='instruction')
        payload = ai.request_payload(claude, 'follow up', history=history)
        self.assertEqual(payload['messages'][:-1], history)
        self.assertEqual(payload['system'], 'instruction')
        self.assertGreater(payload['max_tokens'], 0)
        reply = {'type': 'message', 'stop_reason': 'end_turn', 'content': [
            {'type': 'thinking', 'thinking': 'private thought'}, {'type': 'text', 'text': 'answer'}]}
        self.assertEqual(ai.response_text(reply, 'messages'), 'answer')
        reply['stop_reason'] = 'max_tokens'
        with self.assertRaises(ai.AIError):
            ai.response_text(reply, 'messages')

    def test_native_http_authentication_matches_endpoint_not_provider_label(self):
        ai = self.load('service.ai')
        for provider, header, body in [
            ('gemini', 'x-goog-api-key', {'status': 'completed', 'steps': [
                {'type': 'model_output', 'content': [{'type': 'text', 'text': 'ok'}]}]}),
            ('claude', 'x-api-key', {'type': 'message', 'stop_reason': 'end_turn',
                                    'content': [{'type': 'text', 'text': 'ok'}]})]:
            profile = self.settings.new_profile(provider)
            profile.update(model='test', provider='custom', skill='')
            connection = ai.AIConnection(profile, 'test-key')
            response = Mock(status_code=200)
            response.json.return_value = body
            with patch.object(ai, '_send', return_value=response) as send:
                self.assertEqual(ai.request_ai_text('unused', 'prompt', '', connection=connection), 'ok')
            headers = send.call_args.args[1]
            self.assertEqual(headers[header], 'test-key')
            self.assertNotIn('Authorization', headers)
            if provider == 'claude':
                self.assertEqual(headers['anthropic-version'], '2023-06-01')

    def test_free_json_fragments_validate_and_merge_without_changing_prompt(self):
        ai = self.load('service.ai')
        params = self.load('service.ai_support.parameters')
        self.profile['parameters'] = '"top_p": 1, "content": "继续上文",'
        body = ai.request_payload(self.profile, 'original prompt')
        self.assertEqual(body['input'], 'original prompt')
        self.assertEqual(body['content'], '继续上文')
        self.assertEqual(body['top_p'], 1)
        for invalid in ('[]', '{invalid', '{"top_p":NaN}', '{"messages":[]}', '{"stream":true}'):
            with self.assertRaises(ValueError):
                params.parse_parameters(invalid)
        self.assertEqual(params.parse_parameters('{}'), {})

    def test_complete_endpoint_is_preserved_and_legacy_bases_are_supported(self):
        endpoint = self.load('service.ai_support.parameters').endpoint
        profile = dict(self.profile, base_url='https://example.test/custom/path', endpoint_url=True)
        self.assertEqual(endpoint(profile), profile['base_url'])
        profile.update(base_url='https://example.test/v1', endpoint_url=False)
        self.assertEqual(endpoint(profile), 'https://example.test/v1/responses')
        profile['base_url'] = 'https://example.test/chat/completions'
        self.assertEqual(endpoint(profile), profile['base_url'])

    def test_shared_transport_survives_profile_saves_and_is_snapshotted(self):
        self.settings.save_profiles([self.profile], {self.profile['id']: 'test-credential'})
        self.settings.save_transport(60, 120, 15, 3)
        ai = self.load('service.ai')
        old = ai.snapshot_connection(self.unique)
        self.assertEqual((old.profile['timeout'], old.profile['connect_timeout'], old.profile['retries']), (120, 15, 3))
        self.settings.save_profiles([self.profile], {self.profile['id']: 'test-credential'})
        self.assertEqual(self.settings.ai_send_rate(), 60)
        self.assertEqual(self.settings.transport_settings()['connect_timeout'], 15)
        self.settings.save_transport(30, 50, 5, 0)
        self.assertEqual(old.profile['retries'], 3)
        self.assertEqual(ai.snapshot_connection(self.unique).profile['retries'], 0)

    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.load = self.host.load
        self.settings = self.load('service.ai_config')
        self.profile = self.settings.new_profile('openai')
        self.profile['model'] = 'test-model'
        self.host.config.ai_profiles = [self.profile]
        self.settings._session_keys[self.profile['id']] = 'test-session-key'
        self.unique = 'ai:' + self.profile['id']
        self.host.config.ai_send_mode = 'field'

    def test_presets_and_default_custom_mode(self):
        self.assertEqual(self.profile['temperature'], 1)
        self.assertEqual(self.profile['reasoning'], 'none')
        self.assertNotIn('max_tokens', self.profile)
        for provider in ('openai', 'deepseek', 'qwen', 'custom'):
            self.assertEqual(self.settings.new_profile(provider)['mode'], 'responses')
        self.assertEqual(self.settings.new_profile('gemini')['mode'], 'interactions')
        self.assertEqual(self.settings.new_profile('claude')['mode'], 'messages')

    def test_keys_persist_separately_and_reload_after_restart(self):
        self.profile['api_key'] = 'must-not-save'
        self.settings.save_profiles([self.profile], {self.profile['id']: 'memory-only'})
        saved = self.load('service.ai_store').read_settings()
        self.assertNotIn('api_key', saved['profiles'][0])
        self.assertEqual(saved['keys'][self.profile['id']], 'memory-only')
        self.assertNotIn('must-not-save', str(saved))
        self.assertEqual(self.settings.session_key(self.profile['id']), 'memory-only')
        self.settings.clear_session_keys()
        self.assertEqual(self.settings.session_key(self.profile['id']), 'memory-only')
        store = self.load('service.ai_keys')
        self.assertEqual(store.key_store_path().parent.parent.parent.name,
                         Path(self.host.mw.pm.profileFolder()).name)
        self.assertEqual(json.loads(store.key_store_path().read_text())['keys'][self.profile['id']], 'memory-only')

    def test_clear_key_and_delete_profile_remove_saved_credentials(self):
        self.settings.save_profiles([self.profile], {self.profile['id']: 'saved-key'})
        self.settings.save_profiles([self.profile], {self.profile['id']: ''})
        self.settings.clear_session_keys()
        self.assertEqual(self.settings.session_key(self.profile['id']), '')
        self.settings.save_profiles([self.profile], {self.profile['id']: 'replacement-key'})
        self.settings.save_profiles([], {})
        self.settings.clear_session_keys()
        self.assertEqual(self.settings.session_key(self.profile['id']), '')
        self.assertEqual(self.load('service.ai_keys').read_keys(), {})

    def test_failed_key_write_leaves_profiles_and_old_keys_unchanged(self):
        store = self.load('service.ai_keys')
        store.write_keys({self.profile['id']: 'old-key'})
        self.host.config.update.reset_mock()
        with patch.object(self.load('service.ai_store').os, 'replace', side_effect=PermissionError('secret-detail')):
            with self.assertRaises(ValueError) as error:
                self.settings.save_profiles([self.profile], {self.profile['id']: 'new-key'})
        self.assertNotIn('secret-detail', str(error.exception))
        self.host.config.update.assert_not_called()
        self.assertEqual(store.read_keys()[self.profile['id']], 'old-key')
        self.assertEqual(len(list(store.key_store_path().parent.iterdir())), 1)

    def test_legacy_settings_and_keys_migrate_together(self):
        store = self.load('service.ai_store')
        legacy = store.legacy_keys_path()
        legacy.write_text(json.dumps({self.profile['id']: 'legacy-key'}), encoding='utf-8')
        self.host.config.data = {'ai_profiles': [self.profile], 'ai_thread_number': 7, 'dirs': ['keep']}
        self.assertEqual(self.settings.profiles()[0]['id'], self.profile['id'])
        self.assertEqual(store.read_settings()['keys'][self.profile['id']], 'legacy-key')
        self.settings.save_profiles(self.settings.profiles(), store.read_settings()['keys'], 7)
        self.assertFalse(legacy.exists())
        self.assertNotIn('ai_profiles', self.host.config.data)
        self.assertNotIn('ai_thread_number', self.host.config.data)
        self.assertEqual(self.host.config.data['dirs'], ['keep'])
        self.settings.clear_session_keys()
        self.host.config.ai_profiles = []
        self.assertEqual(self.settings.profiles()[0]['id'], self.profile['id'])
        self.assertEqual(self.settings.ai_send_rate(), 7)
        self.assertEqual(self.settings.session_key(self.profile['id']), 'legacy-key')

    def test_account_settings_are_isolated(self):
        store = self.load('service.ai_store')
        self.settings.save_profiles([self.profile], {self.profile['id']: 'first-account'}, 6)
        first_path = store.settings_path()
        second = first_path.parent.parent.parent / 'second-account'
        second.mkdir()
        self.host.mw.pm.profileFolder = lambda: str(second)
        self.host.config.ai_profiles = []
        self.settings.clear_session_keys()
        self.assertEqual(self.settings.profiles(), [])
        self.assertEqual(self.settings.session_key(self.profile['id']), '')
        self.assertNotEqual(store.settings_path(), first_path)
        self.assertEqual(first_path.parent.name, 'ai')

    def test_invalid_profile_does_not_commit_keys(self):
        self.profile['base_url'] = 'https://example.test/v1?api_key=secret'
        with self.assertRaises(ValueError):
            self.settings.save_profiles([self.profile], {self.profile['id']: 'new-key'})
        self.host.config.update.assert_not_called()
        self.assertEqual(self.settings.session_key(self.profile['id']), 'test-session-key')

    def test_responses_and_chat_payloads(self):
        ai = self.load('service.ai')
        self.profile['parameters'] = {'reasoning': {'effort': 'low'}}
        payload = ai.request_payload(self.profile, 'Explain hello')
        self.assertEqual(payload['input'], 'Explain hello')
        self.assertEqual(payload['reasoning'], {'effort': 'low'})
        self.assertFalse(payload['store'])
        self.assertNotIn('temperature', payload)
        self.profile.update(mode='chat', base_url='https://example.test/chat/completions')
        self.profile['parameters'] = {'reasoning_effort': 'low'}
        payload = ai.request_payload(self.profile, 'Explain hello')
        self.assertEqual(payload['messages'][0]['content'], 'Explain hello')
        self.assertEqual(payload['reasoning_effort'], 'low')
        self.assertNotIn('input', payload)

    def test_skill_is_independent_from_field_prompt_in_both_apis(self):
        ai = self.load('service.ai')
        self.profile['skill'] = '你是英语老师。用中文回答。'
        payload = ai.request_payload(self.profile, '解释 apple')
        self.assertEqual(payload['instructions'], self.profile['skill'])
        self.assertEqual(payload['input'], '解释 apple')
        self.assertFalse(payload['store'])
        self.profile.update(mode='chat', model='gpt-6-luna', base_url='https://example.test/chat/completions')
        payload = ai.request_payload(self.profile, '解释 apple')
        self.assertEqual(payload['messages'][0], {'role': 'system', 'content': self.profile['skill']})
        self.assertEqual(payload['messages'][1], {'role': 'user', 'content': '解释 apple'})
        self.profile.update(provider='deepseek', skill_role='')
        self.assertEqual(ai.request_payload(self.profile, 'hi')['messages'][0]['role'], 'system')
        self.profile['skill_role'] = 'developer'
        self.assertEqual(ai.request_payload(self.profile, 'hi')['messages'][0]['role'], 'developer')

    def test_empty_skill_and_interface_specific_options(self):
        ai = self.load('service.ai')
        self.profile['skill'] = '  \n'
        self.assertNotIn('instructions', ai.request_payload(self.profile, 'hi'))
        self.profile['responses_store'] = True
        self.assertTrue(ai.request_payload(self.profile, 'hi')['store'])
        self.profile['provider'] = 'deepseek'
        self.assertTrue(ai.request_payload(self.profile, 'hi')['store'])
        self.profile.update(mode='chat', base_url='https://example.test/chat/completions')
        payload = ai.request_payload(self.profile, 'hi')
        self.assertEqual(len(payload['messages']), 1)
        self.assertNotIn('store', payload)

    def test_skill_persists_and_old_profiles_get_empty_defaults(self):
        self.profile.update(skill='固定规则\n保持简洁', skill_role='system')
        self.settings.save_profiles([self.profile], {self.profile['id']: 'key'})
        self.settings.clear_session_keys()
        self.assertEqual(self.settings.profiles()[0]['skill'], '固定规则\n保持简洁')
        old = dict(self.profile)
        for key in ('skill', 'skill_role', 'responses_store'):
            old.pop(key)
        self.settings.save_profiles([old], {})
        restored = self.settings.profiles()[0]
        self.assertEqual(restored['skill'], '')
        self.assertEqual(restored['skill_role'], '')
        self.assertFalse(restored['responses_store'])

    def test_usage_logs_actual_counts_for_both_protocols(self):
        diagnostics = self.load('service.ai_support.diagnostics')
        counts = diagnostics.usage({'usage': {'input_tokens': 12, 'output_tokens': 8, 'total_tokens': 20,
            'input_tokens_details': {'cached_tokens': 3}, 'output_tokens_details': {'reasoning_tokens': 4}}}, 'responses')
        self.assertEqual(counts, dict(input=12, output=8, total=20, cached=3, reasoning=4))
        counts = diagnostics.usage({'usage': {'prompt_tokens': 11, 'completion_tokens': 5, 'total_tokens': 16,
            'prompt_cache_hit_tokens': 2, 'completion_tokens_details': {'reasoning_tokens': 1}}}, 'chat')
        self.assertEqual(counts, dict(input=11, output=5, total=16, cached=2, reasoning=1))
        counts = diagnostics.usage({'usage': {'input_tokens': True, 'output_tokens': -1, 'total_tokens': 'secret'}}, 'responses')
        self.assertTrue(all(value is None for value in counts.values()))
        self.assertTrue(all(value is None for value in diagnostics.usage({}, 'chat').values()))

    def test_ai_log_excludes_secrets_and_request_content(self):
        ai = self.load('service.ai')
        self.profile['skill'] = 'private-skill-content'
        requests = sys.modules['requests']
        requests.post.return_value = Mock(status_code=200)
        requests.post.return_value.json.return_value = {'usage': {'input_tokens': 7, 'output_tokens': 3, 'total_tokens': 10},
            'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'private-reply-content'}]}]}
        with self.assertLogs('refactor_tests', level='INFO') as captured, \
                patch.object(ai, 'render_prompt', return_value='private-prompt-content'):
            ai.query_ai(self.unique, 'private-prompt-content', {})
        messages = '\n'.join(captured.output)
        for secret in ('test-session-key', 'private-skill-content', 'private-prompt-content', 'private-reply-content'):
            self.assertNotIn(secret, messages)
        self.assertIn('input=7 output=3 total=10', messages)
        self.assertIn('duration=', messages)
        self.assertIn('request=', messages)

    def test_legacy_ai_imports_share_implementation_identity(self):
        for name in ('config', 'keys', 'store', 'limits', 'models', 'capabilities', 'validation'):
            self.assertIs(self.load('service.ai_' + name), self.load('service.ai_support.' + name))

    def test_english_errors_do_not_translate_user_content(self):
        ai = self.load('service.ai')
        translations = self.load('translations')
        requests = sys.modules['requests']
        requests.post.return_value = Mock(status_code=429)
        with self.load('i18n').use_language('en'), \
                patch.object(ai, '_requests_limit', Mock(acquire=Mock(return_value=True))), \
                patch.object(ai, 'render_prompt', return_value='中文提示词'):
            with self.assertRaises(ai.AIError) as error:
                ai.query_ai(self.unique, '中文提示词', {})
        self.assertIn('Reduce requests per minute', str(error.exception))
        self.profile['skill'] = '中文 Skill'
        self.assertEqual(ai.request_payload(self.profile, '中文任务')['instructions'], '中文 Skill')

    def test_connection_snapshot_survives_profile_edits_and_deletion_without_logging_key(self):
        ai = self.load('service.ai')
        snapshot = ai.snapshot_connection(self.unique)
        self.assertNotIn(snapshot.key, repr(snapshot))
        original_url, original_model = snapshot.profile['base_url'], snapshot.profile['model']
        self.profile.update(base_url='https://changed.test/v1', model='changed-model', skill='changed skill')
        self.settings.save_profiles([], {})
        response = Mock(status_code=200)
        response.json.return_value = {'output': [{'type': 'message', 'role': 'assistant',
            'content': [{'type': 'output_text', 'text': 'saved profile answer'}]}]}
        with patch.object(ai, '_send', return_value=response) as send:
            result = ai.query_ai(self.unique, 'Explain apple', {'Word': 'apple'}, connection=snapshot)
        self.assertIn('saved profile answer', result.result)
        self.assertEqual(send.call_args.args[0], original_url)
        self.assertEqual(send.call_args.args[2]['model'], original_model)
        self.assertEqual(send.call_args.args[1]['Authorization'], 'Bearer ' + snapshot.key)
        with self.assertRaises(ai.AIError):
            ai.query_ai(self.unique, 'Explain apple', {'Word': 'apple'})

    def test_reasoning_none_provider_mapping(self):
        ai = self.load('service.ai')
        parameters = self.load('service.ai_support.parameters')
        for provider, mode, key, value in (
            ('deepseek', 'chat', 'thinking', {'type': 'disabled'}),
            ('deepseek', 'responses', 'reasoning', {'effort': 'none'}),
            ('qwen', 'chat', 'enable_thinking', False),
            ('claude', 'chat', 'thinking', {'type': 'disabled'}),
            ('gemini', 'chat', 'reasoning_effort', 'none')):
            profile = self.settings.new_profile(provider)
            profile.update(mode=mode, base_url='https://example.test/' + ('responses' if mode == 'responses' else 'chat/completions'), parameters=parameters.defaults(provider, mode))
            self.assertEqual(ai.request_payload(profile, 'hi')[key], value)

    def test_no_output_cap_even_for_old_profiles(self):
        ai = self.load('service.ai')
        self.profile['max_tokens'] = 1
        for mode in ('responses', 'chat'):
            self.profile['mode'] = mode
            payload = ai.request_payload(self.profile, 'hi')
            for key in ('max_tokens', 'max_completion_tokens', 'max_output_tokens'):
                self.assertNotIn(key, payload)

    def test_custom_parameters_are_not_filtered_by_model_policy(self):
        ai = self.load('service.ai')
        for provider, model in [('deepseek', 'any'), ('openai', 'gpt-6.1-sol'), ('gemini', 'gemini-3.8-flash')]:
            self.profile.update(provider=provider, model=model, parameters={'temperature': 1, 'reasoning': {'effort': 'none'}, 'top_p': .8})
            payload = ai.request_payload(self.profile, 'hi')
            self.assertEqual(payload['temperature'], 1)
            self.assertEqual(payload['reasoning'], {'effort': 'none'})
            self.assertEqual(payload['top_p'], .8)

    def test_response_only_extracts_answer_not_reasoning(self):
        ai = self.load('service.ai')
        data = {'status': 'completed', 'output': [
            {'type': 'reasoning', 'content': [{'type': 'reasoning_text', 'text': 'private thought'}]},
            {'type': 'message', 'content': [{'type': 'output_text', 'text': '**Answer**'}]},
        ]}
        self.assertEqual(ai.response_text(data, 'responses'), '**Answer**')
        data['status'] = 'incomplete'
        with self.assertRaises(ai.AIError):
            ai.response_text(data, 'responses')
        with self.assertRaises(ai.AIError):
            ai.response_text({'choices': [{'finish_reason': 'length', 'message': {'content': 'partial'}}]}, 'chat')

    def test_request_endpoint_and_markdown(self):
        ai = self.load('service.ai')
        # The pure host fixture replaces BeautifulSoup at the dependency boundary.
        with patch.object(ai, 'render_prompt', return_value='Explain hello'):
            requests = sys.modules['requests']
            requests.post.return_value = Mock(status_code=200)
            requests.post.return_value.json.return_value = {'status': 'completed', 'output': [
                {'type': 'message', 'content': [{'type': 'output_text', 'text': '**Hello**'}]}]}
            result = ai.query_ai(self.unique, '{{Word}}', {'Word': 'hello'})
        self.assertEqual(result.result, '<p><strong>Hello</strong></p>')
        args = requests.post.call_args
        self.assertEqual(args.args[0], 'https://api.openai.com/v1/responses')
        self.assertFalse(args.kwargs['allow_redirects'])
        self.assertEqual(args.kwargs['headers']['Authorization'], 'Bearer test-session-key')

    def test_http_errors_never_include_secret_response_body(self):
        ai = self.load('service.ai')
        requests = sys.modules['requests']
        requests.post.return_value = Mock(status_code=401, text='test-session-key')
        with patch.object(ai, 'render_prompt', return_value='hello'):
            with self.assertRaises(ai.AIError) as error:
                ai.query_ai(self.unique, 'hello', {})
        self.assertNotIn('test-session-key', str(error.exception))
        self.assertIn('401', str(error.exception))

    def test_markdown_basics_and_escaping(self):
        convert = self.load('utils.markdown').markdown_to_html
        html = convert('# Title\n\n**bold** and *italic*\n\n- first\n- second\n\n```html\n<script>x</script>\n```')
        for element in ('<h1>Title</h1>', '<strong>bold</strong>', '<em>italic</em>', '<ul>', '<pre><code>'):
            self.assertIn(element, html)
        self.assertNotIn('<script>', html)
        self.assertNotIn('class=', html)
        self.assertNotIn('href="javascript:', convert('[bad](javascript:alert)'))
        self.assertIn('<table>', convert('| A | B |\n| --- | --- |\n| a | b |'))

    def test_missing_field_or_key_prevents_request(self):
        ai = self.load('service.ai')
        with self.assertRaises(ai.AIError):
            ai.render_prompt('{{Missing}}', {})
        self.settings.clear_session_keys()
        with self.assertRaises(ai.AIError):
            ai.query_ai(self.unique, 'hi', {})
        sys.modules['requests'].post.assert_not_called()

    def query_module(self):
        package = types.ModuleType(support.PACKAGE + '.query')
        package.__path__ = [str(support.SRC / 'query')]
        sys.modules[package.__name__] = package
        sys.modules[support.PACKAGE + '.libs'].__path__ = [str(support.SRC / 'libs')]
        sys.modules[support.PACKAGE + '.constants'].Template = Mock()
        base = self.load('service.base')
        sys.modules[support.PACKAGE + '.service'].QueryResult = base.QueryResult
        sys.modules[support.PACKAGE + '.service'].copy_static_file = base.copy_static_file
        self.host.config.ignore_accents = False
        self.host.config.force_update = False
        self.host.config.cloze_str = '{{c1::%s}}'
        return self.load('query.common')

    def note_and_maps(self):
        class Note:
            fields = ['', 'old', 'example']
            def note_type(self):
                return {'id': 1, 'flds': [{'name': name} for name in ('Word', 'Meaning', 'Example')],
                        'tmpls': [{'afmt': '{{Meaning}}'}]}
        maps = [{'word_checked': True},
                {'fld_ord': 1, 'dict_unique': self.unique, 'dict_fld_ord': 0,
                 'ignore': False, 'skip_valued': False, 'ai_prompt': 'Explain {{Example}}'},
                {'ignore': True}]
        self.host.config.get_maps = lambda model: maps
        return Note(), maps

    def test_query_ai_works_with_empty_word_and_updates_target(self):
        common = self.query_module()
        note, maps = self.note_and_maps()
        result_class = self.load('service.result').QueryResult
        with patch.object(common, 'query_ai', return_value=result_class(result='<p>answer</p>')) as query:
            results, successes, missed = common.query_flds(note)
        self.assertEqual(successes, 1)
        self.assertEqual(missed, [])
        self.assertEqual(query.call_args.args[2], {'Word': '', 'Meaning': 'old', 'Example': 'example'})
        self.assertEqual(common.update_note_fields(note, results), 1)
        self.assertEqual(note.fields[1], '<p>answer</p>')

    def test_skip_and_field_filter_do_not_send_ai_requests(self):
        common = self.query_module()
        note, maps = self.note_and_maps()
        maps[1]['skip_valued'] = True
        with patch.object(common, 'query_ai') as query:
            common.query_flds(note)
            query.assert_not_called()
            maps[1]['skip_valued'] = False
            common.query_flds(note, fileds=[2])
            query.assert_not_called()

    def test_failed_ai_never_clears_original_field(self):
        common = self.query_module()
        note, maps = self.note_and_maps()
        self.host.config.force_update = True
        with patch.object(common, 'query_ai', side_effect=ValueError('safe failure')):
            results, successes, missed = common.query_flds(note)
        self.assertEqual(successes, 0)
        self.assertEqual(common.update_note_fields(note, results), 0)
        self.assertEqual(note.fields[1], 'old')

    def test_cancelled_ai_does_not_send_request(self):
        ai = self.load('service.ai')
        with patch.object(ai, 'render_prompt', return_value='hello'):
            with self.assertRaises(ai.AIError):
                ai.query_ai(self.unique, 'hello', {}, cancelled=lambda: True)
        sys.modules['requests'].post.assert_not_called()
        # Cancellation must release the concurrency permit for later queries.
        self.assertTrue(ai._requests_limit.acquire(blocking=False))
        ai._requests_limit.release()

    def test_smooth_rate_does_not_accumulate_burst_permits(self):
        self.host.config.thread_number = 1
        self.assertEqual(self.settings.ai_send_rate(), 29)
        now = [0.0]
        rate = [60]
        limit = self.load('service.ai_limits').AIRequestLimiter(clock=lambda: now[0], rate=lambda: rate[0])
        self.assertTrue(limit.acquire(blocking=False))
        limit.release()
        self.assertFalse(limit.acquire(blocking=False))
        now[0] = 0.99
        self.assertFalse(limit.acquire(blocking=False))
        now[0] = 1.0
        self.assertTrue(limit.acquire(blocking=False))
        limit.release()
        now[0] = 120.0
        self.assertTrue(limit.acquire(blocking=False))
        limit.release()
        self.assertFalse(limit.acquire(blocking=False))
        rate[0] = 120
        now[0] += 0.5
        self.assertTrue(limit.acquire(blocking=False))
        limit.release()
        limit.defer(5)
        now[0] += 4.9
        self.assertFalse(limit.acquire(blocking=False))
        now[0] += 0.1
        self.assertTrue(limit.acquire(blocking=False))

    def test_active_ceiling_queues_and_cancel_does_not_take_a_slot(self):
        now = [0.0]
        limit = self.load('service.ai_limits').AIRequestLimiter(clock=lambda: now[0], rate=lambda: 600, max_active=1)
        self.assertTrue(limit.acquire(blocking=False))
        now[0] = 10
        self.assertFalse(limit.acquire(blocking=False))
        limit.release()
        self.assertFalse(limit.acquire(cancelled=lambda: True))
        self.assertTrue(limit.acquire(blocking=False))

    def test_send_rate_is_saved_and_old_concurrency_is_not_reinterpreted(self):
        store = self.load('service.ai_store')
        store.write_settings({'profiles': [self.profile], 'keys': {}, 'thread_number': 4})
        self.assertEqual(self.settings.ai_send_rate(), 29)
        self.settings.save_profiles([self.profile], {self.profile['id']: 'memory'}, requests_per_minute=120)
        data = store.read_settings()
        self.assertEqual(data['requests_per_minute'], 120)
        self.assertNotIn('thread_number', data)
        self.assertEqual(self.host.config.update.call_args.args[0]['ai_settings']['requests_per_minute'], 120)

    def test_transient_http_retries_are_bounded_and_reenter_pacing(self):
        ai = self.load('service.ai')
        requests = sys.modules['requests']
        first = Mock(status_code=429, headers={'Retry-After': '3'})
        final = Mock(status_code=200, headers={})
        final.json.return_value = {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'ok'}]}]}
        limiter = Mock(acquire=Mock(return_value=True))
        requests.post.side_effect = [first, final]
        with patch.object(ai, '_requests_limit', limiter), patch.object(ai, 'render_prompt', return_value='hello'):
            self.assertEqual(ai.query_ai(self.unique, 'hello', {}).result, '<p>ok</p>')
        self.assertEqual(limiter.acquire.call_count, 2)
        self.assertEqual(limiter.release.call_count, 2)
        limiter.defer.assert_called_once_with(3)
        requests.post.side_effect = None
        requests.post.return_value = Mock(status_code=503, headers={})
        requests.post.reset_mock()
        with patch.object(ai, '_requests_limit', limiter), patch.object(ai, 'render_prompt', return_value='hello'):
            with self.assertRaises(ai.AIError):
                ai.query_ai(self.unique, 'hello', {})
        self.assertEqual(requests.post.call_count, 3)
        requests.post.return_value = Mock(status_code=401, headers={})
        requests.post.reset_mock()
        with patch.object(ai, '_requests_limit', limiter), patch.object(ai, 'render_prompt', return_value='hello'):
            with self.assertRaises(ai.AIError):
                ai.query_ai(self.unique, 'hello', {})
        self.assertEqual(requests.post.call_count, 1)

    def test_retry_policy_honors_server_delay_and_rejects_long_automatic_waits(self):
        retry = self.load('service.ai_support.retry')
        self.assertEqual(retry.retry_delay(Mock(status_code=429, headers={'Retry-After': '10'}), 0), 10)
        self.assertIsNone(retry.retry_delay(Mock(status_code=429, headers={'Retry-After': '120'}), 0))
        self.assertIsNone(retry.retry_delay(Mock(status_code=503, headers={}), 2))
        self.assertIsNone(retry.retry_delay(Mock(status_code=400, headers={}), 0))

    def test_connection_settings_validate_persist_and_default_for_older_profiles(self):
        self.profile.pop('connect_timeout')
        self.profile.pop('retries')
        self.settings.save_profiles([self.profile], {})
        saved = self.settings.profiles()[0]
        self.assertEqual((saved['connect_timeout'], saved['retries']), (10, 2))
        self.profile.update(connect_timeout=7, retries=0)
        self.settings.save_profiles([self.profile], {})
        saved = self.settings.profiles()[0]
        self.assertEqual((saved['connect_timeout'], saved['retries']), (7, 0))
        for key, values in (('connect_timeout', (0, 61, True, 1.5, '10')),
                            ('retries', (-1, 6, True, 1.5, '2'))):
            for value in values:
                with self.assertRaises(ValueError):
                    self.settings.validate_profile(dict(self.profile, **{key: value}))

    def test_custom_retry_budget_and_connection_timeout_reach_the_transport(self):
        ai = self.load('service.ai')
        requests = sys.modules['requests']
        limiter = Mock(acquire=Mock(return_value=True))
        self.profile['connect_timeout'] = 7
        for retries in (0, 4):
            self.profile['retries'] = retries
            requests.post.return_value = Mock(status_code=503, headers={})
            requests.post.reset_mock()
            with patch.object(ai, '_requests_limit', limiter), patch.object(ai, 'render_prompt', return_value='hello'):
                with self.assertRaises(ai.AIError):
                    ai.query_ai(self.unique, 'hello', {})
            self.assertEqual(requests.post.call_count, retries + 1)
            self.assertEqual(requests.post.call_args.kwargs['timeout'], (7, 90))
        requests.post.return_value = Mock(status_code=401, headers={})
        requests.post.reset_mock()
        with patch.object(ai, '_requests_limit', limiter), patch.object(ai, 'render_prompt', return_value='hello'):
            with self.assertRaises(ai.AIError):
                ai.query_ai(self.unique, 'hello', {})
        requests.post.assert_called_once()

    def test_waiting_for_send_can_be_cancelled_quickly(self):
        import threading
        import time
        limit = self.load('service.ai_limits').AIRequestLimiter(rate=lambda: 1)
        self.assertTrue(limit.acquire())
        limit.release()
        cancel = threading.Event()
        result = []
        thread = threading.Thread(target=lambda: result.append(limit.acquire(cancelled=cancel.is_set)))
        thread.start()
        cancel.set()
        thread.join(0.5)
        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [False])

    def test_ai_output_field_references_are_rejected(self):
        validate = self.load('service.ai_validation').validate_ai_references
        names = ['Word', 'Meaning', 'Example']
        maps = [{'word_checked': True}, {'fld_ord': 1, 'dict_unique': 'ai:first'},
                {'fld_ord': 2, 'dict_unique': 'ai:second', 'ignore': True}]
        validate('Explain {{Word}}', maps, names)
        for template in ('{{Meaning}}', '{{ Example }}', '{{Word}} {{Meaning}}'):
            with self.assertRaisesRegex(ValueError, 'AI 输出字段'):
                validate(template, maps, names)

    def test_old_ai_mapping_reference_is_blocked_before_request(self):
        common = self.query_module()
        note, maps = self.note_and_maps()
        maps[1]['ai_prompt'] = 'Explain {{Meaning}}'
        with patch.object(common, 'query_ai') as query:
            results, successes, missed = common.query_flds(note)
        query.assert_not_called()
        self.assertEqual(successes, 0)
        self.assertFalse(results)


if __name__ == '__main__':
    unittest.main()
