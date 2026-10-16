"""Credential access within the unified local AI configuration file."""

from .store import settings_path, read_settings, write_settings


def key_store_path():
    return settings_path()


def read_keys():
    return read_settings().get('keys', {})


def write_keys(keys):
    data = read_settings()
    data['keys'] = keys
    write_settings(data)
