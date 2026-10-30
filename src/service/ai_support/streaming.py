"""Read SSE text with terminal-state validation; never accept partial output."""
import json


def collect(response, mode, error, cancelled=None, on_delta=None):
    chunks, ended, reason = [], False, None
    terminal = None
    steps = {}
    def events():
        data = []
        for line in response.iter_lines(chunk_size=1):
            if cancelled and cancelled():
                raise error('AI 任务已取消。', code='cancelled')
            line = line.decode('utf-8') if isinstance(line, bytes) else line
            if not line:
                if data:
                    yield '\n'.join(data)
                    data = []
            elif line.startswith('data:'):
                data.append(line[5:].lstrip())
        if data:
            yield '\n'.join(data)
    try:
        for raw in events():
            if raw == '[DONE]':
                break
            event = json.loads(raw)
            kind = event.get('type', event.get('event_type', ''))
            if event.get('error') or kind in ('error', 'response.failed', 'response.incomplete'):
                raise error('AI 流式回复失败或未完整生成。', code='incomplete_response')
            text = ''
            if mode == 'chat':
                for choice in event.get('choices', []):
                    if choice.get('index', 0) != 0:
                        continue
                    text = choice.get('delta', {}).get('content') or ''
                    if choice.get('finish_reason'):
                        ended, reason = True, choice['finish_reason']
            elif mode == 'responses':
                if kind == 'response.output_text.delta':
                    text = event.get('delta', '')
                elif kind == 'response.completed':
                    terminal = event.get('response')
                    ended = True
            elif mode == 'messages':
                if kind == 'content_block_delta' and event.get('delta', {}).get('type') == 'text_delta':
                    text = event['delta'].get('text', '')
                elif kind == 'message_delta':
                    reason = event.get('delta', {}).get('stop_reason', reason)
                elif kind == 'message_stop':
                    ended = True
            elif mode == 'interactions':
                if kind == 'step.start':
                    steps[event.get('index')] = event.get('step', {}).get('type')
                elif kind == 'step.delta' and steps.get(event.get('index')) == 'model_output':
                    delta = event.get('delta', {})
                    if delta.get('type') == 'text':
                        text = delta.get('text', '')
                elif kind == 'interaction.completed':
                    ended = event.get('interaction', {}).get('status') == 'completed'
            if text:
                chunks.append(text)
                if on_delta:
                    on_delta(text)
        if not ended:
            raise error('AI 流式连接中断，回复未完整生成。', code='incomplete_response')
        if mode == 'chat' and reason not in ('stop', 'length', 'content_filter'):
            raise error('AI 回复未完成文本生成。', code='incomplete_response')
        text = ''.join(chunks)
        if mode == 'responses' and terminal is not None:
            return terminal
        if mode == 'chat':
            return {'choices': [{'message': {'content': text}, 'finish_reason': reason}]}
        if mode == 'messages':
            return {'type': 'message', 'stop_reason': reason, 'content': [{'type': 'text', 'text': text}]}
        if mode == 'interactions':
            return {'status': 'completed', 'steps': [{'type': 'model_output', 'content': [{'type': 'text', 'text': text}]}]}
        return {'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': text}]}]}
    finally:
        response.close()
