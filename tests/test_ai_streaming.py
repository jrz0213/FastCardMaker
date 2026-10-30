import importlib.util
import json
from pathlib import Path
import unittest


def load(name):
    path = Path(__file__).resolve().parents[1] / 'src/service/ai_support' / (name + '.py')
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Error(ValueError):
    def __init__(self, text, code):
        super().__init__(text)
        self.code = code


class Response:
    def __init__(self, events):
        self.events, self.closed = events, False

    def iter_lines(self, **kwargs):
        for event in self.events:
            yield ('data: ' + json.dumps(event, ensure_ascii=False)).encode('utf-8')
            yield b''

    def close(self):
        self.closed = True


class StreamingTests(unittest.TestCase):
    def test_chat_deltas_and_completion(self):
        response = Response([{'choices': [{'delta': {'content': '你好'}}]},
                             {'choices': [{'delta': {}, 'finish_reason': 'stop'}]}])
        parts = []
        result = load('streaming').collect(response, 'chat', Error, on_delta=parts.append)
        self.assertEqual(parts, ['你好'])
        self.assertEqual(result['choices'][0]['message']['content'], '你好')
        self.assertTrue(response.closed)

    def test_disconnect_and_cancel_never_publish_partial_output(self):
        for cancelled in (None, lambda: True):
            response = Response([{'choices': [{'delta': {'content': 'partial'}}]}])
            with self.assertRaises(Error):
                load('streaming').collect(response, 'chat', Error, cancelled)
            self.assertTrue(response.closed)

    def test_responses_uses_terminal_response(self):
        final = {'status': 'completed', 'output': [], 'usage': {'input_tokens': 3}}
        result = load('streaming').collect(Response([{'type': 'response.completed', 'response': final}]), 'responses', Error)
        self.assertEqual(result, final)

    def test_claude_and_gemini(self):
        events = [{'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'hello'}},
                  {'type': 'message_delta', 'delta': {'stop_reason': 'end_turn'}}, {'type': 'message_stop'}]
        result = load('streaming').collect(Response(events), 'messages', Error)
        self.assertEqual(result['content'][0]['text'], 'hello')
        events = [{'event_type': 'step.start', 'index': 1, 'step': {'type': 'model_output'}},
                  {'event_type': 'step.delta', 'index': 1, 'delta': {'type': 'text', 'text': 'hello'}},
                  {'event_type': 'interaction.completed', 'interaction': {'status': 'completed'}}]
        result = load('streaming').collect(Response(events), 'interactions', Error)
        self.assertEqual(result['steps'][0]['content'][0]['text'], 'hello')

    def test_incremental_objects_and_escaped_text(self):
        cards = [{'topic': 'A', 'content': 'escaped "cards": [ and 中文'}, {'topic': 'B', 'content': 'second'}]
        text = json.dumps({'ai_message': 'start', 'changes': [{'action': 'add', 'cards': cards}]}, ensure_ascii=False)
        reader = load('incremental').complete_cards
        first_end = text.index('}, {') + 1
        self.assertEqual(reader(text[:first_end]), cards[:1])
        for i in range(len(text) + 1):
            result = reader(text[:i])
            self.assertIn(len(result), (0, 1, 2))
            self.assertEqual(result, cards[:len(result)])
        self.assertEqual(reader(text), cards)


if __name__ == '__main__':
    unittest.main()
