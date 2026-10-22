"""AI connection profiles and locally persisted credentials."""

from ...translations import text as tr

from copy import deepcopy
from threading import RLock
from urllib.parse import urlsplit
from uuid import uuid4

from .parameters import defaults as parameter_defaults, parameters_for, parse_parameters
from .keys import read_keys
from .store import read_settings, write_settings, remove_legacy_settings

PRESETS = {
    'openai': ('ChatGPT / OpenAI', 'https://api.openai.com/v1/responses', 'responses'),
    'deepseek': ('DeepSeek', 'https://api.deepseek.com/responses', 'responses'),
    'qwen': (tr('Qwen / 百炼'), 'https://maas.qianwenaiapi.com/compatible-mode/v1/responses', 'responses'),
    'gemini': ('Gemini', 'https://generativelanguage.googleapis.com/v1beta/interactions', 'interactions'),
    'claude': ('Claude', 'https://api.anthropic.com/v1/messages', 'messages'),
    'custom': (tr('自定义'), '', 'responses'),
}
PROFILE_FIELDS = ('id', 'name', 'provider', 'base_url', 'mode', 'model', 'interface_format',
                  'temperature', 'reasoning', 'timeout', 'connect_timeout', 'retries',
                  'skill', 'skill_role', 'responses_store', 'send_mode', 'parameters', 'endpoint_url')
_session_keys = {}
_key_lock = RLock()


def new_profile(provider='custom'):
    name, address, mode = PRESETS[provider]
    return dict(id=uuid4().hex, name=name, provider=provider, base_url=address,
                mode=mode, model='', temperature=1,
                reasoning='none', timeout=90, skill='', skill_role='', responses_store=False,
                send_mode='field', connect_timeout=10, retries=2, endpoint_url=True,
                parameters=parameter_defaults(provider, mode))


def profiles():
    stored = read_settings(include_keys=False)
    value = stored.get('profiles', [])
    items = deepcopy(value) if isinstance(value, list) else []
    for item in items:
        item.setdefault('send_mode', 'field')
        if isinstance(stored.get('transport'), dict):
            item.update(stored['transport'])
    return items


def profile_choices():
    keys = read_settings().get('keys', {})
    return [{'title': item['name'] + ' · ' + item['model'] + ('' if keys.get(item['id']) else ' (' + tr('缺失 API Key') + ')'), 'unique': 'ai:' + item['id']}
            for item in profiles()]


DEFAULT_REQUESTS_PER_MINUTE = 29
MAX_IN_FLIGHT = 32


def ai_send_rate():
    try:
        return max(1, min(600, int(read_settings(include_keys=False).get('requests_per_minute', DEFAULT_REQUESTS_PER_MINUTE))))
    except (TypeError, ValueError):
        return DEFAULT_REQUESTS_PER_MINUTE


def ai_thread_count():
    """Compatibility access to the internal worker ceiling, not a setting."""
    return MAX_IN_FLIGHT


def is_ai(unique):
    return isinstance(unique, str) and unique.startswith('ai:')


def profile_for(unique):
    return next((item for item in profiles() if 'ai:' + item['id'] == unique), None)


def validate_profile(item):
    if not item.get('name', '').strip() or not item.get('model', '').strip():
        raise ValueError(tr('请填写配置名称和模型名称。'))
    url = urlsplit(item.get('base_url', ''))
    if url.scheme not in ('https', 'http') or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError(tr('API 地址应是完整的 http(s) 基础地址，不能含密钥、查询参数或用户名。'))
    from .parameters import protocol
    protocol(item)
    parameters_for(item)
    if type(item.get('connect_timeout', 10)) is not int or not 1 <= item.get('connect_timeout', 10) <= 60:
        raise ValueError(tr('连接超时应为 1 到 60 秒。'))
    if type(item.get('retries', 2)) is not int or not 0 <= item.get('retries', 2) <= 5:
        raise ValueError(tr('自动重试次数应为 0 到 5。'))
    if not 1 <= int(item.get('timeout', 90)) <= 600:
        raise ValueError(tr('请求超时超出允许范围。'))
    if not isinstance(item.get('skill', ''), str):
        raise ValueError(tr('Skill 应为文本。'))
    if item.get('skill_role', '') not in ('', 'system', 'developer'):
        raise ValueError(tr('Skill 指令角色无效。'))
    if not isinstance(item.get('responses_store', False), bool):
        raise ValueError(tr('回复保存选项无效。'))
    if item.get('send_mode', 'field') not in ('field', 'note'):
        raise ValueError(tr('请选择逐字段发送或按笔记合并发送。'))


def save_profiles(items, keys, requests_per_minute=None):
    safe = []
    for item in items:
        validate_profile(item)
        defaults = dict(skill='', skill_role='', responses_store=False, send_mode='field',
                        connect_timeout=10, retries=2)
        saved = {key: item.get(key, defaults.get(key)) for key in PROFILE_FIELDS if key not in ('temperature', 'reasoning')}
        saved['parameters'] = parameters_for(item)
        from .parameters import protocol
        saved['mode'] = protocol(item)
        safe.append(saved)
    data = read_settings()
    data.update(profiles=safe, requests_per_minute=ai_send_rate())
    data.pop('thread_number', None)
    if requests_per_minute is not None:
        if not 1 <= int(requests_per_minute) <= 600:
            raise ValueError(tr('每分钟发送数应为 1 到 600。'))
        data['requests_per_minute'] = int(requests_per_minute)
    with _key_lock:
        saved_keys = {item['id']: keys.get(item['id'], '').strip() for item in safe}
        data['keys'] = saved_keys
        write_settings(data)
        _session_keys.clear()
        _session_keys.update(saved_keys)
        remove_legacy_settings()


def session_key(profile_id):
    with _key_lock:
        if profile_id not in _session_keys:
            return read_keys().get(profile_id, '')
        return _session_keys.get(profile_id, '')


def clear_session_keys():
    """Forget in-memory overrides; persisted credentials remain available."""
    with _key_lock:
        _session_keys.clear()


def transport_settings():
    stored = read_settings(include_keys=False)
    old = next(iter(stored.get('profiles', [])), {})
    values = stored.get('transport', old)
    return {key: values.get(key, default) for key, default in
            (('timeout', 90), ('connect_timeout', 10), ('retries', 2))}


def save_transport(rate, timeout, connect_timeout, retries, backup_api_keys=None):
    values = dict(timeout=timeout, connect_timeout=connect_timeout, retries=retries)
    validate_profile(dict(name='transport', model='transport', base_url='https://example.invalid', mode='chat', **values))
    if type(rate) is not int or not 1 <= rate <= 600:
        raise ValueError(tr('每分钟发送数应为 1 到 600。'))
    data = read_settings()
    data.update(transport=values, requests_per_minute=rate)
    write_settings(data, backup_api_keys=backup_api_keys)
