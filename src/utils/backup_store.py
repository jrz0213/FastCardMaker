"""One portable ZIP for AI/mapping settings and Python parsers; local paths stay local."""
from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from threading import RLock
import zipfile

LOCK = RLock()
BASIC_KEYS = {'ui_language', 'backup_mode', 'backup_api_keys', 'enable_logging',
              'thread_number', 'force_update', 'ignore_accents', 'ignore_mdx_wordcase',
              'fuzzy_match', 'cloze_str', 'sound_str', 'auto_run', 'ai_send_mode',
              'ai_markdown', 'ai_css_enabled', 'ai_css', 'ai_styles', 'use_filename', 'export_media'}


def archive_path():
    from .media import media_directory
    return Path(media_directory()) / '_fastcm_backup.zip'


def read_bundle(path=None):
    path = Path(path or archive_path())
    if not path.exists():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 1100 or sum(e.file_size for e in entries) > 32 * 1024 * 1024:
                raise ValueError('Backup is too large')
            if len({e.filename for e in entries}) != len(entries):
                raise ValueError('Duplicate backup entries')
            allowed = {'settings.json', 'manifest.json'}
            if any(e.filename not in allowed and not e.filename.startswith('scripts/') for e in entries):
                raise ValueError('Unexpected backup entry')
            settings = json.loads(archive.read('settings.json').decode('utf-8')) if 'settings.json' in archive.namelist() else {}
            manifest = json.loads(archive.read('manifest.json').decode('utf-8')) if 'manifest.json' in archive.namelist() else {}
            from .config_storage import validate_settings
            validate_settings(settings)
            scripts = {e.filename[len('scripts/'):]: {'source': archive.read(e).decode('utf-8')}
                       for e in entries if e.filename.startswith('scripts/')}
            from ..service.script_library import validate
            validate(scripts)
            return {'settings': settings, 'scripts': scripts,
                    'initialized': bool(manifest.get('scripts_initialized', bool(scripts)))}
    except (zipfile.BadZipFile, UnicodeError, KeyError, SyntaxError, TypeError) as error:
        raise ValueError('Invalid FastCard Maker backup') from error


def write_bundle(path=None, settings=None, scripts=None):
    target = Path(path or archive_path())
    with LOCK:
        signature = (target.stat().st_mtime_ns, target.stat().st_size) if target.exists() else None
        previous = read_bundle(target) or {'settings': {}, 'scripts': {}, 'initialized': False}
        # Never erase an old backup's only key when the system vault refuses
        # migration, even if the caller supplies an otherwise clean replacement.
        from ..service.ai_support.migration import scrub, _profiles
        from ..context import config
        catalogue = _profiles(getattr(config, 'data', {}))
        previous['settings'] = scrub(previous['settings'], catalogue)
        if settings is not None:
            from .config_storage import portable, validate_settings
            previous['settings'] = portable(scrub(validate_settings(deepcopy(settings)), catalogue))
        previous['settings'].pop('credential_backup', None)
        if scripts is not None:
            from ..service.script_library import validate
            validate(scripts)
            previous['scripts'] = deepcopy(scripts)
            previous['initialized'] = True
        target.parent.mkdir(parents=True, exist_ok=True)
        settings_text = json.dumps(previous['settings'], ensure_ascii=False, allow_nan=False)
        if len(settings_text.encode('utf-8')) + sum(len(item['source'].encode('utf-8')) for item in previous['scripts'].values()) > 32 * 1024 * 1024 - 4096:
            raise ValueError('Backup is too large')
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.fastcm-backup-', delete=False) as stream:
                temporary = stream.name
                with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('manifest.json', json.dumps({'format': 'fastcm-backup', 'version': 1,
                        'scripts_initialized': previous['initialized']}))
                    archive.writestr('settings.json', settings_text)
                    for name, item in sorted(previous['scripts'].items()):
                        archive.writestr('scripts/' + name, item['source'])
                stream.flush()
                os.fsync(stream.fileno())
            current = (target.stat().st_mtime_ns, target.stat().st_size) if target.exists() else None
            if current != signature:
                raise ValueError('Backup changed during saving; local settings were preserved.')
            os.replace(temporary, target)
        finally:
            if temporary and os.path.exists(temporary):
                os.remove(temporary)


def shared_configuration(basic_path):
    from .config_storage import read_object
    data = read_object(basic_path)
    archive = read_bundle(Path(basic_path).parent / '_fastcm_backup.zip')
    if archive is not None:
        data = dict(archive['settings'], **data)
    return data


def save_shared(basic_path, settings):
    from .config_storage import atomic_write
    # Only AI connections accompany Python scripts. Preferences and mappings
    # (including script enable flags) live in the media configuration JSON.
    write_bundle(Path(basic_path).parent / '_fastcm_backup.zip', settings={key: value for key, value in settings.items() if key == 'ai_settings'})
    atomic_write(basic_path, preferences(settings))


def preferences(settings):
    return {key: value for key, value in settings.items() if key not in ('ai_settings', 'credential_backup')}


def automatic():
    from ..context import config
    data = getattr(config, 'data', {})
    return not isinstance(data, dict) or data.get('backup_mode', 'auto') != 'manual'
