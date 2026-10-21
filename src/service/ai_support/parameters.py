"""User-editable JSON request parameters; no model capability filtering."""
import json
from urllib.parse import urlsplit
from copy import deepcopy
from ...translations import text as tr


def defaults(provider, mode):
    if mode == 'interactions':
        return {'generation_config': {'temperature': 1, 'thinking_level': 'minimal'}}
    if mode == 'messages':
        return {'temperature': 1, 'thinking': {'type': 'disabled'}, 'max_tokens': 4096}
    data = {'temperature': 1}
    if provider in ('deepseek', 'claude') and mode == 'chat':
        data['thinking'] = {'type': 'disabled'}
    elif provider == 'qwen' and mode != 'responses':
        data['enable_thinking'] = False
    elif mode == 'responses':
        data['reasoning'] = {'effort': 'none'}
    else:
        data['reasoning_effort'] = 'none'
    return data


def parse_parameters(value):
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return {}
        if not value.startswith('{'):
            value = '{' + value.rstrip().rstrip(',') + '}'
        try:
            value = json.loads(value, parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
        except (ValueError, TypeError):
            raise ValueError(tr('自由参数必须是有效的 JSON 对象，可填写完整对象或键值片段。')) from None
    if not isinstance(value, dict):
        raise ValueError(tr('自由参数必须是 JSON 对象。'))
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        raise ValueError(tr('自由参数包含无效的 JSON 值。')) from None
    if any(key in value for key in ('model', 'messages', 'input', 'instructions', 'system', 'system_instruction', 'api_key', 'authorization', 'headers')):
        raise ValueError(tr('模型、消息正文和认证由插件填写，请勿在自由参数中覆盖。'))
    if value.get('stream', False) is not False:
        raise ValueError(tr('当前仅支持非流式请求，stream 必须为 false。'))
    return deepcopy(value)


def parameters_for(profile):
    if 'parameters' in profile:
        return parse_parameters(profile['parameters'])
    # Compatibility for existing profiles, preserving explicitly saved values.
    data = {}
    if profile.get('temperature') is not None:
        data['temperature'] = profile['temperature']
    effort = profile.get('reasoning', '')
    if effort:
        provider, mode = profile.get('provider'), profile.get('mode')
        if provider in ('deepseek', 'claude') and mode == 'chat':
            data['thinking'] = {'type': 'disabled' if effort == 'none' else 'enabled'}
            if effort != 'none' and provider == 'deepseek':
                data['reasoning_effort'] = effort
        elif provider == 'qwen' and mode == 'chat':
            data['enable_thinking'] = effort != 'none'
        elif mode == 'responses':
            data['reasoning'] = {'effort': effort}
        else:
            data['reasoning_effort'] = effort
    return data


def endpoint(profile):
    address = profile.get('base_url', '').rstrip('/')
    if profile.get('endpoint_url') or address.endswith(('/responses', '/chat/completions', '/interactions', '/messages')):
        return address
    return address + ('/responses' if profile.get('mode') == 'responses' else '/chat/completions')


def protocol(profile):
    """The endpoint decides the wire format, including legacy saved profiles."""
    path = urlsplit(endpoint(profile)).path.rstrip('/')
    for suffix, mode in (('/responses', 'responses'), ('/chat/completions', 'chat'),
                         ('/interactions', 'interactions'), ('/messages', 'messages')):
        if path.endswith(suffix):
            return mode
    raise ValueError(tr('无法识别接口地址，请填写以 /responses、/chat/completions、/interactions 或 /messages 结尾的完整地址。'))
