"""Local AI connection settings; ZIP archives are reserved for backups."""
from pathlib import Path
from .config_storage import atomic_write, read_object, portable


def cache_path():
    from aqt import mw
    return Path(mw.pm.profileFolder()) / 'fastcm' / 'ai' / 'settings.json'


def read_cache():
    path = cache_path()
    if not path.exists():
        return None
    data = read_object(path)
    if not isinstance(data.get('profiles', []), list):
        raise ValueError('Invalid AI settings')
    return data


def write_cache(data):
    data = portable(data)
    if read_cache() == data:
        return
    atomic_write(cache_path(), data)
