"""Small declarative equivalents of dictionary JavaScript audio path rules."""
import re
from urllib.parse import unquote

from .dictionary_assets import local_key, read_asset

AUDIO_EXTENSIONS = {'.mp3', '.wav', '.ogg', '.aac', '.spx', '.m4a', '.flac'}


def validate_audio_rule(rule):
    if not isinstance(rule, dict) or set(rule) != {'attribute', 'steps'}:
        raise ValueError()
    if not isinstance(rule['attribute'], str) or not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_-]{0,60}', rule['attribute']):
        raise ValueError()
    if not isinstance(rule['steps'], list) or len(rule['steps']) > 12:
        raise ValueError()
    for step in rule['steps']:
        if not isinstance(step, dict):
            raise ValueError()
        op = step.get('op')
        expected = {'prefix': {'op', 'value'}, 'suffix': {'op', 'value'},
                    'replace': {'op', 'old', 'new'}, 'decode_uri': {'op'},
                    'lower': {'op'}, 'call_argument': {'op', 'function'}, 'map': {'op', 'values'}}.get(op)
        if expected is None or set(step) != expected:
            raise ValueError()
        if op == 'map':
            values = step['values']
            if not isinstance(values, dict) or not 1 <= len(values) <= 200:
                raise ValueError()
            if any(not isinstance(k, str) or not isinstance(v, str) or len(k) > 1000 or len(v) > 1000 for k, v in values.items()):
                raise ValueError()
        else:
            if any(not isinstance(value, str) or len(value) > 1000 for key, value in step.items() if key != 'op'):
                raise ValueError()
            if op == 'replace' and not step['old']:
                raise ValueError()
            if op == 'call_argument' and not re.fullmatch(r'[a-zA-Z_$][\w$]*(?:\.[a-zA-Z_$][\w$]*)*', step['function']):
                raise ValueError()


def audio_path(node, rule):
    value = node.get(rule['attribute'])
    if not isinstance(value, str) or len(value) > 8000:
        raise ValueError('Missing audio source')
    for step in rule['steps']:
        op = step['op']
        if op == 'prefix':
            value = step['value'] + value
        elif op == 'suffix':
            value += step['value']
        elif op == 'replace':
            value = value.replace(step['old'], step['new'])
        elif op == 'decode_uri':
            value = unquote(value)
        elif op == 'lower':
            value = value.lower()
        elif op == 'map':
            value = step['values'][value]
        elif op == 'call_argument':
            match = re.fullmatch(r'\s*(?:javascript:\s*)?' + re.escape(step['function']) +
                                 r'\s*\(\s*([\'"])([^\'"\\\r\n]*)\1\s*\)\s*;?\s*(?:return\s+false\s*;?\s*)?', value)
            if not match:
                raise ValueError('Unsupported audio call')
            value = match.group(2)
        if len(value) > 8000:
            raise ValueError('Audio path too long')
    if value.startswith('sound:'):
        value = value[6:]
    key = local_key(value)
    if '.' + key.rsplit('.', 1)[-1].lower() not in AUDIO_EXTENSIONS:
        raise ValueError('Unsupported audio resource')
    return key


def extract_audio(soup, nodes, rule, builder=None, dict_path=None):
    links, seen = [], set()
    for node in nodes:
        try:
            key = audio_path(node, rule)
        except (ValueError, KeyError):
            raise ValueError('Cannot resolve dictionary audio') from None
        if key in seen:
            continue
        if builder is not None and not read_asset(builder, dict_path, key, 1):
            raise ValueError('Dictionary audio resource missing')
        seen.add(key)
        link = soup.new_tag('a', href='sound:' + key)
        link.string = node.get_text(' ', strip=True) or '▶'
        links.append(str(link))
    return '<br>'.join(links)
