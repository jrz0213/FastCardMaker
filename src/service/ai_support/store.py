"""Profile-local credentials, with portable AI settings in the shared config."""

from ...translations import text as tr

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlsplit

from aqt import mw
from ...context import config

AI_ROOT = Path(__file__).resolve().parent.parent / 'ai'


def settings_path():
    return Path(mw.pm.profileFolder()) / 'fastcm' / 'ai' / 'config.json'


def legacy_keys_path():
    return Path(mw.pm.profileFolder()) / '_fastwq_ai_keys.json'


def read_settings():
    try:
        path = settings_path()
        if path.exists():
            with path.open(encoding='utf-8') as file:
                data = json.load(file)
        elif (AI_ROOT / Path(mw.pm.profileFolder()).name / 'config.json').exists():
            with (AI_ROOT / Path(mw.pm.profileFolder()).name / 'config.json').open(encoding='utf-8') as file:
                data = json.load(file)
        else:
            keys = {}
            if legacy_keys_path().exists():
                with legacy_keys_path().open(encoding='utf-8') as file:
                    keys = json.load(file)
            data = dict(profiles=getattr(config, 'ai_profiles', []),
                        requests_per_minute=29, keys=keys)
        shared = getattr(config, 'ai_settings', None)
        if isinstance(shared, dict):
            keys = deepcopy(data.get('keys', {}))
            previous = {item['id']: item for item in data.get('profiles', []) if isinstance(item, dict) and 'id' in item}
            for item in shared.get('profiles', []):
                old = previous.get(item.get('id'), {})
                if old.get('base_url'):
                    before, after = urlsplit(old['base_url']), urlsplit(item.get('base_url', ''))
                    if (before.scheme, before.netloc) != (after.scheme, after.netloc):
                        keys.pop(item.get('id'), None)
            data = dict(deepcopy(shared), keys=keys)
        if not isinstance(data, dict) or not isinstance(data.get('profiles', []), list):
            raise ValueError()
        keys = data.get('keys', {})
        if not isinstance(keys, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                            for k, v in keys.items()):
            raise ValueError()
        return data
    except (OSError, ValueError):
        raise ValueError(tr('无法读取 AI 配置文件，请检查文件权限或格式。')) from None


def write_settings(data):
    path = settings_path()
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.fastwq_ai-', delete=False) as file:
            temporary = Path(file.name)
            os.chmod(temporary, 0o600)
            json.dump(data, file, ensure_ascii=False, indent=2)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
        from ...utils.config_storage import portable
        config.update({'ai_settings': portable(data)})
    except OSError:
        raise ValueError(tr('无法保存 AI 配置，请检查当前 Anki 用户文件夹的写入权限。')) from None
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def remove_legacy_settings():
    """Called only after a complete new file has been saved."""
    try:
        data = getattr(config, 'data', None)
        if isinstance(data, dict) and ('ai_profiles' in data or 'ai_thread_number' in data):
            previous = dict(data)
            data.pop('ai_profiles', None)
            data.pop('ai_thread_number', None)
            try:
                config.update({})
            except Exception:
                data.clear()
                data.update(previous)
                raise
        legacy_keys_path().unlink(missing_ok=True)
    except Exception:
        raise ValueError(tr('AI 配置已保存到新目录，但旧配置清理失败，请检查旧文件写入权限。')) from None
