import json
from pathlib import Path
import tempfile
import unittest

import test_modularization as support


class ScriptInformationTests(unittest.TestCase):
    def setUp(self):
        self.host = support.RefactorTests()
        self.host.setUp()
        self.addCleanup(self.host.doCleanups)
        self.info = self.host.load('service.script_information')

    def test_history_is_complete_ordered_and_excludes_payload_attachments(self):
        records = [{'kind': 'request', 'user_message': f'fix {i}', 'response': f'reply {i}',
                    'payload': {'html': 'HEAVY_ATTACHMENT'}} for i in range(5)]
        records.append({'kind': 'debug', 'response': 'not a chat reply'})
        history = self.info.compact_history(records)
        self.assertEqual([m['content'] for m in history], [part for i in range(5) for part in (f'fix {i}', f'reply {i}')])
        self.assertNotIn('HEAVY_ATTACHMENT', json.dumps(history))
        full = self.info.compact_history([{'user_message': 'u' * 5000, 'response': 'r' * 100000}])
        self.assertEqual(full[0]['content'], 'u' * 5000)
        self.assertEqual(full[1]['content'], 'r' * 100000)

    def test_redaction_and_portable_export_keep_request_reply_and_local_errors(self):
        record = self.info.request_record('model', 'internal instructions', {'html': '<b>entry</b>'},
                                         {'messages': [{'role': 'user', 'content': 'private-key'}]}, 'fix', 'dict')
        record['response'] = 'invalid JSON reply private-key'
        record['local'] = {'traceback': 'Traceback: missing audio'}
        clean = self.info.redact(record, 'private-key')
        text = self.info.portable_markdown([clean, {'kind': 'debug', 'error': 'missing.mp3'}])
        self.assertNotIn('private-key', text)
        self.assertIn('[REDACTED]', text)
        self.assertIn('invalid JSON reply', text)
        self.assertIn('Traceback: missing audio', text)
        self.assertIn('missing.mp3', text)

    def test_history_reload_filters_dictionary_and_prefers_completed_snapshot(self):
        updates = self.host.load('service.script_updates')
        with tempfile.TemporaryDirectory() as temp:
            updates.write_conversation({'id': 'one', 'dictionary_id': 'a', 'state': 'sending'}, temp)
            updates.write_conversation({'id': 'one', 'dictionary_id': 'a', 'state': 'completed', 'response': 'full reply'}, temp)
            updates.write_conversation({'id': 'other', 'dictionary_id': 'b', 'response': 'other dictionary'}, temp)
            records = self.info.load_history(temp, 'a')
            self.assertEqual(len(records), 1)
            self.assertEqual(records[0]['response'], 'full reply')
            self.assertEqual(self.info.load_history(temp, 'a', cancelled=lambda: True), [])

    def test_debug_feedback_bounds_success_output_without_truncating_local_record(self):
        record = {'rows': [{'result': 'x' * 5000, 'error': 'missing audio', 'traceback': 'full trace'}]}
        feedback = self.info.debug_feedback(record)
        self.assertEqual(len(feedback['rows'][0]['result']), 2000)
        self.assertTrue(feedback['rows'][0]['result_truncated'])
        self.assertEqual(len(record['rows'][0]['result']), 5000)
        self.assertEqual(feedback['rows'][0]['traceback'], 'full trace')

    def test_chat_and_responses_payloads_include_real_history_messages(self):
        ai = self.host.load('service.ai')
        profile = self.host.load('service.ai_config').new_profile('custom')
        profile.update(model='test-model', skill='')
        history = [{'role': 'user', 'content': 'prior question'}, {'role': 'assistant', 'content': 'prior answer'}]
        for mode in ('chat', 'responses'):
            profile.update(mode=mode, base_url='https://example.test/' + ('responses' if mode == 'responses' else 'chat/completions'))
            payload = ai.request_payload(profile, 'current request', 'parser instructions', history=history)
            messages = payload['messages'] if mode == 'chat' else payload['input']
            self.assertEqual([m['content'] for m in messages if m['role'] in ('user', 'assistant')],
                             ['prior question', 'prior answer', 'current request'])
            self.assertEqual(history[-1]['content'], 'prior answer')

    def test_session_listing_and_import_are_dictionary_scoped_and_unlimited(self):
        updates = self.host.load('service.script_updates')
        with tempfile.TemporaryDirectory() as temp:
            for i in range(35):
                updates.write_conversation({'id': str(i), 'dictionary_id': 'a', 'session_id': 'session-one',
                                            'time': '2026-10-16', 'response': str(i)}, temp)
            updates.write_conversation({'id': 'legacy', 'dictionary_id': 'a', 'response': 'legacy'}, temp)
            updates.write_conversation({'id': 'foreign', 'dictionary_id': 'b', 'session_id': 'session-other'}, temp)
            sessions = self.info.history_sessions(temp, 'a')
            self.assertEqual({s['id'] for s in sessions}, {'session-one', 'legacy'})
            rows = self.info.load_history(temp, 'a', session_id='session-one')
            self.assertEqual(len(rows), 35)
            self.assertEqual([r['response'] for r in rows], [str(i) for i in range(35)])
            self.assertEqual(len(self.info.load_history(temp, 'a', session_id='legacy')), 1)
