"""Portable settings omit credentials, machine paths and scheduler cursors."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import tempfile

LOCAL_KEYS = {'dirs', 'last_folder', 'last_model', '_auto_run_state', 'version',
              'path', 'dict_path', 'mdx_path', 'script_path', 'script_paths',
              'api_key', 'keys', 'ai_thread_number'}


def portable(value):
    if isinstance(value, dict):
        return {key: deepcopy(item) if key == 'parameters' else portable(item) for key, item in value.items()
                if key not in LOCAL_KEYS and not key.endswith('_last')}
    if isinstance(value, list):
        return [portable(item) for item in value]
    return deepcopy(value)


def restore_portable(shared, local):
    """Replace shared values, retaining machine-only values at their old keys."""
    result = deepcopy(shared)
    for key, value in local.items():
        if key in LOCAL_KEYS or key.endswith('_last'):
            result[key] = deepcopy(value)
        elif isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = restore_portable(result[key], value)
    return result


def fingerprint(value):
    return hashlib.sha256(json.dumps(portable(value), ensure_ascii=False,
                                     sort_keys=True, allow_nan=False).encode('utf-8')).hexdigest()


def read_object(path, default=None):
    try:
        with Path(path).open(encoding='utf-8') as stream:
            result = json.load(stream)
    except FileNotFoundError:
        return deepcopy(default if default is not None else {})
    if not isinstance(result, dict):
        raise ValueError('Invalid FastCard Maker configuration')
    return result


def validate_settings(value, importing=False):
    if not isinstance(value, dict):
        raise ValueError('Invalid configuration object')
    for key in ('dicts', 'auto_run', 'ai_styles', 'ai_settings'):
        if key in value and not isinstance(value[key], dict):
            raise ValueError('Invalid configuration section')
    if any(not isinstance(item, dict) for item in value.get('dicts', {}).values()):
        raise ValueError('Invalid dictionary settings')
    if 'ai_settings' in value:
        profiles = value['ai_settings'].get('profiles', [])
        if not isinstance(profiles, list) or any(not isinstance(item, dict) or
                any(not isinstance(item.get(key), str) for key in ('id', 'name', 'model')) for item in profiles):
            raise ValueError('Invalid AI profiles')
    for key, item in value.items():
        if key.isdigit() and not isinstance(item, (dict, list)):
            raise ValueError('Invalid note type configuration')
        if key.isdigit() and isinstance(item, dict):
            tabs = item.get('list', [])
            if not isinstance(tabs, list):
                raise ValueError('Invalid configuration tabs')
            for tab in tabs:
                if isinstance(tab, dict) and not isinstance(tab.get('name'), str):
                    raise ValueError('Invalid tab name')
                fields = tab.get('fields', []) if isinstance(tab, dict) else tab
                if not isinstance(fields, list) or any(not isinstance(field, dict) for field in fields):
                    raise ValueError('Invalid field mapping')
    if importing:
        known = {'ai_settings', 'ai_profiles', 'ai_styles', 'ai_css', 'ai_css_enabled',
                 'ai_markdown', 'ai_send_mode', 'ui_language', 'dicts', 'auto_run',
                 'thread_number', 'force_update', 'ignore_accents', 'ignore_mdx_wordcase',
                 'fuzzy_match', 'use_filename', 'export_media', 'cloze_str', 'sound_str', 'enable_logging'}
        if not any(key in known or key.isdigit() for key in portable(value)):
            raise ValueError('Not a FastCard Maker configuration')
    return value


def atomic_write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.fastcm-', delete=False) as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)
