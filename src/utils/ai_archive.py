"""Atomic local ZIP cache for AI connection metadata, never credentials."""
import json
import os
from pathlib import Path
import tempfile
import zipfile


def cache_path():
    from aqt import mw
    return Path(mw.pm.profileFolder()) / 'fastcm' / 'ai' / 'settings.zip'


def read_cache():
    path = cache_path()
    if not path.exists():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) != 1 or entries[0].filename != 'settings.json' or entries[0].file_size > 4 * 1024 * 1024:
                raise ValueError('Invalid AI settings ZIP')
            data = json.loads(archive.read('settings.json'))
        if not isinstance(data, dict) or not isinstance(data.get('profiles', []), list):
            raise ValueError('Invalid AI settings ZIP')
        return data
    except (zipfile.BadZipFile, KeyError, UnicodeError) as error:
        raise ValueError('Invalid AI settings ZIP') from error


def write_cache(data):
    from .config_storage import portable
    data = portable(data)
    if read_cache() == data:
        return
    path = cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.fastcm-ai-', delete=False) as stream:
            temporary = stream.name
            os.chmod(temporary, 0o600)
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                archive.writestr('settings.json', json.dumps(data, ensure_ascii=False, allow_nan=False))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)
