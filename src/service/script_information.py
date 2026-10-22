"""Portable, credential-free information records and compact chat context."""
from copy import deepcopy
from datetime import datetime, timezone
import json
import uuid
import hashlib
import re
from pathlib import Path


def redact(value, secret=''):
    text = json.dumps(value, ensure_ascii=False)
    if secret:
        text = text.replace(json.dumps(secret, ensure_ascii=False)[1:-1], '[REDACTED]')
    return json.loads(text)


def hide_local_paths(value, dictionary_path):
    """Keep filenames in AI diagnostics without sending local root directories."""
    from pathlib import Path
    import tempfile
    from ..utils.media import media_directory
    roots = [(str(Path(dictionary_path).resolve().parent), '<dictionary>'),
             (str(Path(media_directory()).parent), '<profile>'),
             (str(Path(__file__).resolve().parent.parent), '<addon>'),
             (tempfile.gettempdir(), '<temporary>')]
    def clean(item):
        if isinstance(item, str):
            for root, label in sorted(roots, key=lambda pair: len(pair[0]), reverse=True):
                for spelling in {root, root.replace('\\', '/'), root.replace('/', '\\'),
                                 json.dumps(root, ensure_ascii=False)[1:-1]}:
                    if len(spelling) > 3:
                        item = item.replace(spelling, label)
            return item
        if isinstance(item, dict):
            return {key: clean(content) for key, content in item.items()}
        if isinstance(item, list):
            return [clean(content) for content in item]
        return item
    return clean(value)


def request_record(model, instructions, request, payload, user_message, dictionary_id):
    return {'id': uuid.uuid4().hex, 'kind': 'request', 'time': datetime.now(timezone.utc).isoformat(),
            'dictionary_id': dictionary_id, 'model': model, 'instructions': instructions,
            'user_message': user_message, 'request': request, 'payload': payload,
            'response': '', 'state': 'sending', 'local': {}}


def selected_context(records, selected=None):
    """Conversation turns stay in history; local observations are current attachments."""
    history, information = [], []
    for index, record in enumerate(records):
        kind = record.get('kind', 'request')
        chosen = lambda role: selected is None or '%s-%s' % (index, role) in selected
        if kind == 'request':
            if chosen('user'):
                history.append({'role': 'user', 'content': str(record.get('user_message') or
                    record.get('request', {}).get('user_command', ''))})
            if record.get('response') and chosen('assistant'):
                history.append({'role': 'assistant', 'content': str(record['response'])})
            if record.get('local') and chosen('local'):
                information.append({'id': record.get('id', str(index)), 'kind': 'local',
                    'time': record.get('time', ''), 'data': deepcopy(record['local'])})
        elif kind == 'context':
            if chosen('user'):
                history.append({'role': 'user', 'content': str(record.get('content', ''))})
        elif chosen('debug' if kind == 'debug' else 'local'):
            information.append({'id': record.get('id', str(index)), 'kind': kind,
                'time': record.get('time', ''), 'data': deepcopy(record)})
    return history, information


def deduplicate_scripts(request, history):
    """Keep one exact copy of a script, retaining references at every other location."""
    value = deepcopy(request)
    known = {}
    def fingerprint(source):
        return hashlib.sha256(source.strip().encode('utf-8')).hexdigest()
    for index, turn in enumerate(history):
        if turn.get('role') != 'assistant':
            continue
        content = turn.get('content', '')
        source = content
        try:
            parsed = json.loads(content)
            source = parsed.get('code', '') if isinstance(parsed, dict) else ''
        except (ValueError, TypeError):
            fence = re.fullmatch(r'```(?:python|py)?\s*\n([\s\S]*?)\n```', content.strip())
            source = fence.group(1) if fence else content
        if isinstance(source, str) and source.strip():
            known[fingerprint(source)] = 'history[%s].content' % index
    def source_once(item, key, location):
        source = item.get(key)
        if not isinstance(source, str) or not source.strip():
            return
        digest = fingerprint(source)
        if digest in known:
            item.pop(key)
            item[key + '_reference'] = {'sha256': digest, 'location': known[digest]}
        else:
            known[digest] = location + '.' + key
    if isinstance(value.get('current_script'), dict):
        source_once(value['current_script'], 'source', 'current_script')
    for index, item in enumerate(value.get('original_scripts', [])):
        source_once(item, 'source', 'original_scripts[%s]' % index)
    for index, item in enumerate(value.get('local_information', [])):
        if isinstance(item.get('data'), dict):
            source_once(item['data'], 'generated_script', 'local_information[%s].data' % index)
    return value


def compact_history(records):
    """Send every conversation turn verbatim, without recursively repeating attachments."""
    messages = []
    for record in records:
        if record.get('kind') == 'context':
            messages.append({'role': 'user', 'content': 'Imported conversation (reference only):\n' + str(record.get('content', ''))})
            continue
        if record.get('kind', 'request') != 'request' or not record.get('response'):
            continue
        user = str(record.get('user_message') or record.get('request', {}).get('user_command', ''))
        messages.extend([{'role': 'user', 'content': user},
                         {'role': 'assistant', 'content': str(record['response'])}])
    return messages


def portable_markdown(records):
    sections = ['# FastCard Maker — Information history', '']
    for index, record in enumerate(records, 1):
        sections += ['## %s. %s · %s' % (index, record.get('kind', 'request'), record.get('time', '')), '']
        if record.get('kind') not in (None, 'request'):
            sections += ['### Local debug result' if record.get('kind') == 'debug' else '### Local processing',
                         '', '````json', json.dumps(record, ensure_ascii=False, indent=2), '````', '']
        else:
            sections += ['### Exact request body (no authentication headers)', '', '````json',
                         json.dumps(record.get('payload', {'instructions': record.get('instructions'), 'request': record.get('request')}), ensure_ascii=False, indent=2),
                         '````', '', '### Raw AI reply', '', record.get('response') or '[No reply received]', '',
                         '### Local processing', '', '````json', json.dumps(record.get('local', {}), ensure_ascii=False, indent=2), '````', '']
    return '\n'.join(sections)


def load_history(directory, dictionary_id, limit=None, cancelled=None, session_id=None):
    from .script_updates import history_directory
    records = {}
    files = sorted(history_directory(directory).glob('conversation_*.json'), reverse=True)
    for path in files:
        if cancelled and cancelled():
            break
        try:
            if path.is_symlink():
                continue
            value = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        if not isinstance(value, dict) or value.get('dictionary_id') != dictionary_id:
            continue
        if session_id is not None and value.get('session_id', 'legacy') != session_id:
            continue
        key = value.get('id') or path.stem
        if key not in records:
            value['id'], value['storage_saved'] = key, True
            records[key] = value
        if limit is not None and len(records) >= limit:
            break
    return list(reversed(list(records.values())))


def history_sessions(directory, dictionary_id, cancelled=None):
    groups = {}
    for record in load_history(directory, dictionary_id, cancelled=cancelled):
        key = record.get('session_id', 'legacy')
        group = groups.setdefault(key, {'id': key, 'time': record.get('time', ''), 'count': 0})
        group['count'] += 1
    return list(reversed(list(groups.values())))


def debug_feedback(report):
    """Keep full local records; send bounded diagnostic context to the model."""
    value = deepcopy(report)
    for row in value.get('rows', []):
        output = row.get('result', '')
        if len(output) > 2000:
            row['result'] = output[:2000]
            row['result_truncated'] = True
    if len(value.get('files', [])) > 40:
        value['file_count'] = len(value['files'])
        value['files'] = value['files'][:40]
        value['files_truncated'] = True
    return value
