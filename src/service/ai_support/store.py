"""AI metadata in ZIP; complete API keys in the operating system vault."""
import json
import os
from copy import deepcopy
from pathlib import Path
from aqt import mw
from ...context import config
from ...translations import text as tr
from ...utils.ai_archive import cache_path, read_cache, write_cache
from . import credentials

AI_ROOT = Path(__file__).resolve().parent.parent / 'ai'


def settings_path():
    return cache_path()


def legacy_keys_path():
    return Path(mw.pm.profileFolder()) / '_fastwq_ai_keys.json'


def _legacy():
    paths = [cache_path().with_name('config.json'), AI_ROOT / Path(mw.pm.profileFolder()).name / 'config.json']
    for path in paths:
        if path.exists():
            return json.loads(path.read_text(encoding='utf-8'))
    keys = json.loads(legacy_keys_path().read_text(encoding='utf-8')) if legacy_keys_path().exists() else {}
    return dict(profiles=getattr(config, 'ai_profiles', []), requests_per_minute=29, keys=keys)


def read_settings(include_keys=True):
    try:
        data = read_cache()
        legacy = _legacy() if data is None else {}
        data = deepcopy(data if data is not None else legacy)
        shared = getattr(config, 'ai_settings', None)
        if isinstance(shared, dict):
            data.update(deepcopy(shared))
        if not isinstance(data.get('profiles', []), list):
            raise ValueError()
        old_keys = legacy.get('keys', {})
        old_backup = getattr(config, 'data', {}).get('credential_backup', {})
        keys = {}
        if not include_keys:
            return dict(data, keys={})
        for profile in data.get('profiles', []):
            key = credentials.read(profile)
            if not key:
                previous = next((p for p in legacy.get('profiles', []) if p.get('id') == profile['id']), None)
                if previous is None or credentials.identifier(previous) == credentials.identifier(profile):
                    key = old_keys.get(profile['id'], '') or old_backup.get(profile['id'], '')
            if not isinstance(key, str) or key.startswith('fastcm-key-'):
                raise ValueError()
            if key:
                keys[profile['id']] = key
        return dict(data, keys=keys)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        raise ValueError(tr('无法读取 AI 配置或系统凭证库，原配置未更改。')) from None


def write_settings(data, backup_api_keys=None):
    from ...utils.config_storage import portable
    data = deepcopy(data)
    previous = read_settings()
    previous_cache = read_cache()
    changed = []
    try:
        for profile in data.get('profiles', []):
            key = data.get('keys', {}).get(profile['id'], '')
            if not isinstance(key, str):
                raise ValueError('Invalid API key')
            old = credentials.read(profile)
            if old != key:
                changed.append((profile, old))
                credentials.write(profile, key)
        write_cache(portable(data))
        config.update({'ai_settings': portable(data), 'backup_api_keys': False, 'credential_backup': {}})
    except (OSError, ValueError):
        for profile, key in reversed(changed):
            credentials.write(profile, key)
        if previous_cache is not None:
            write_cache(previous_cache)
        elif settings_path().exists():
            settings_path().unlink()
        raise ValueError(tr('无法保存 AI 配置或系统凭证，原密钥已保留。')) from None
    current = {credentials.identifier(p) for p in data.get('profiles', [])}
    for profile in previous.get('profiles', []):
        if credentials.identifier(profile) not in current:
            credentials.write(profile, '')


def remove_legacy_settings():
    """Delete only obsolete local key files after credentials were saved safely."""
    try:
        data = getattr(config, 'data', None)
        if isinstance(data, dict) and ('ai_profiles' in data or 'ai_thread_number' in data):
            data.pop('ai_profiles', None)
            data.pop('ai_thread_number', None)
            config.update({})
        from .migration import scrub, _profiles
        for path in (legacy_keys_path(), cache_path().with_name('config.json')):
            if path.exists():
                scrub(json.loads(path.read_text(encoding='utf-8')), _profiles(read_cache() or {}),
                      keys_only=path == legacy_keys_path())
                path.unlink()
    except (OSError, ValueError):
        raise ValueError(tr('AI 配置已保存，但旧配置清理失败，请检查旧文件权限。')) from None
