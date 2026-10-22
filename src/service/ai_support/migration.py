"""Migrate known legacy plaintext files only after an OS-vault read-back."""
from copy import deepcopy
import hashlib
from pathlib import Path

from aqt import mw
from ...context import config
from ...utils import system_password
from ...utils.config_storage import atomic_write, read_object
from ...utils.logger import logger
from . import credentials


def _profiles(data):
    if not isinstance(data, dict):
        return []
    result = [p for p in data.get('profiles', []) if isinstance(p, dict) and isinstance(p.get('id'), str)]
    result += [p for p in data.get('ai_profiles', []) if isinstance(p, dict) and isinstance(p.get('id'), str)]
    for name in ('settings', 'ai_settings'):
        result += _profiles(data.get(name))
    return result


def _save(profile, key):
    if not isinstance(key, str) or not key:
        return
    if key.startswith('fastcm-key-'):
        raise ValueError('Legacy encrypted credential needs explicit recovery')
    name = credentials.identifier(profile)
    previous = system_password.read(name)
    if previous and previous != key:
        # Preserve an older backup's distinct key without replacing today's key.
        name += '|legacy:' + hashlib.sha256(key.encode('utf-8')).hexdigest()
    system_password.write(key, name)
    if system_password.read(name) != key:
        raise ValueError('Credential read-back failed')


def scrub(data, catalogue, keys_only=False):
    result = deepcopy(data)
    def visit(section):
        own = _profiles(section)
        known = own or catalogue
        def save(identifier, key):
            candidates = [p for p in known if p['id'] == identifier]
            origins = {credentials.identifier(p) for p in candidates}
            if len(origins) != 1:
                raise ValueError('Cannot associate legacy API key with a unique connection')
            _save(candidates[0], key)
        names = ['credential_backup']
        if 'profiles' in section:
            names.append('keys')
        for name in names:
            if name in section:
                keys = section[name]
                if not isinstance(keys, dict):
                    raise ValueError('Invalid legacy credentials')
                for identifier, key in keys.items():
                    if key:
                        save(identifier, key)
                section.pop(name)
        for profile in section.get('profiles', []) + section.get('ai_profiles', []):
            if isinstance(profile, dict) and profile.get('api_key'):
                _save(profile, profile['api_key'])
                profile.pop('api_key')
        for name in ('settings', 'ai_settings'):
            if isinstance(section.get(name), dict):
                visit(section[name])
        if 'backup_api_keys' in section:
            section['backup_api_keys'] = False
    if keys_only:
        wrapper = {'credential_backup': result}
        visit(wrapper)
        return {}
    visit(result)
    return result


def migrate_plaintext():
    from .store import AI_ROOT, legacy_keys_path
    from ...utils.ai_archive import cache_path, write_cache
    from ...utils.backup_store import read_bundle, write_bundle
    account = Path(mw.pm.profileFolder())
    media = account / 'collection.media'
    paths = {account / '_fastcm_local.json', account / '_fastcm_local.previous.json',
             cache_path(), cache_path().with_name('config.json'), legacy_keys_path(),
             AI_ROOT / account.name / 'config.json'}
    paths.update(media / name for name in ('_fastcmcfg.json', '.fastcmcfg.json', '_fastwqcfg.json', '.fastwqcfg.json'))
    records = []
    for path in sorted(paths):
        if path.is_file():
            try:
                records.append((path, read_object(path), False, path.stat().st_mtime_ns))
            except (OSError, ValueError):
                logger.warning('Credential migration skipped unreadable configuration: %s', path.name)
    for path in sorted(media.glob('_fastcm_*.zip')):
        if path.name == '_fastcm_scripts.zip':
            continue  # Legacy archive contains only root-level .py files, no keys.
        try:
            bundle = read_bundle(path)
            if bundle is not None:
                records.append((path, bundle['settings'], True, path.stat().st_mtime_ns))
        except (OSError, ValueError, SyntaxError):
            logger.warning('Credential migration skipped unreadable backup: %s', path.name)
    catalogue = _profiles(getattr(config, 'data', {}))
    for _, data, _, _ in records:
        catalogue += _profiles(data)
    changed = 0
    for path, data, archive, signature in records:
        try:
            cleaned = scrub(data, catalogue, keys_only=path == legacy_keys_path())
            if cleaned == data:
                continue
            if path.stat().st_mtime_ns != signature:
                raise ValueError('Configuration changed during credential migration')
            if archive:
                write_bundle(path, settings=cleaned)
            elif path == cache_path().with_name('config.json'):
                write_cache(cleaned)
                path.unlink()
            elif path == legacy_keys_path() and not cleaned:
                path.unlink()
            else:
                atomic_write(path, cleaned)
            changed += 1
        except (OSError, ValueError, TypeError, KeyError):
            logger.warning('Credential migration incomplete; original file retained: %s', path.name)
    if changed:
        logger.info('Moved legacy credentials to OS vault and cleaned %d configuration/backup files', changed)
        config.read(force=True)
    return changed
