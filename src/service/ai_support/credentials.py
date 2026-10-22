"""API keys live in the OS vault, scoped to an Anki profile and API origin."""
from urllib.parse import urlsplit
from ...utils import system_password


def identifier(profile):
    url = urlsplit(profile.get('base_url', ''))
    return str(profile['id']) + '|' + url.scheme.lower() + '://' + url.netloc.lower()


def read(profile):
    return system_password.read(identifier(profile)) or ''


def write(profile, key):
    if key:
        system_password.write(key, identifier(profile))
        if system_password.read(identifier(profile)) != key:
            raise OSError('System credential read-back failed')
    else:
        system_password.delete(identifier(profile))
        if system_password.read(identifier(profile)):
            raise OSError('System credential deletion failed')


def migrate_backup(settings, overwrite=False):
    """Read old plaintext backups once without ever writing keys back to media."""
    profiles = settings.get('ai_settings', {}).get('profiles', settings.get('ai_profiles', []))
    old = settings.get('credential_backup', {})
    if isinstance(old, dict):
        known = {profile.get('id') for profile in profiles}
        if any(key and (identifier not in known or not isinstance(key, str) or key.startswith('fastcm-key-'))
               for identifier, key in old.items()):
            raise ValueError('Legacy credentials need explicit recovery before saving')
        for profile in profiles:
            key = old.get(profile.get('id'))
            if isinstance(key, str) and key and not key.startswith('fastcm-key-') and (overwrite or not read(profile)):
                write(profile, key)
    settings.pop('credential_backup', None)
    settings['backup_api_keys'] = False
