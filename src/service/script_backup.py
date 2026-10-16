"""Content-based synchronization of a flat Python-only media ZIP."""
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
import zipfile

from .script_library import script_directory, snapshot, validate
from ..utils.config_storage import atomic_write, read_object
from ..utils.media import media_directory

_matched = {}


def backup_path():
    return Path(media_directory()) / '_fastcm_scripts.zip'


def digest(files):
    manifest = [(name, len(item['source'].encode('utf-8')), sha256(item['source'].encode('utf-8')).hexdigest())
                for name, item in sorted(files.items())]
    return sha256(json.dumps(manifest, ensure_ascii=False).encode('utf-8')).hexdigest()


def read_backup():
    path = backup_path()
    if not path.exists():
        return None
    try:
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 1024 or sum(item.file_size for item in entries) > 32 * 1024 * 1024:
                raise ValueError('Script backup is too large')
            if len({item.filename for item in entries}) != len(entries):
                raise ValueError('Duplicate script names')
            result = {item.filename: {'source': archive.read(item).decode('utf-8')} for item in entries}
        validate(result)
        return result
    except (zipfile.BadZipFile, UnicodeError, SyntaxError, KeyError) as error:
        raise ValueError('Invalid script backup') from error


def write_backup(files):
    validate(files)
    target = backup_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent, prefix='.fastcm-scripts-', delete=False) as stream:
            temporary = stream.name
            with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
                for name, item in sorted(files.items()):
                    archive.writestr(name, item['source'])
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    finally:
        if temporary and os.path.exists(temporary):
            os.remove(temporary)


def state_path():
    return script_directory() / '.sync-state.json'


def initialize():
    local = snapshot(script_directory())
    remote = read_backup()
    if remote is None:
        if local:
            write_backup(local)
            atomic_write(state_path(), {'baseline': digest(local)})
            _matched[str(script_directory())] = digest(local)
    elif local == remote:
        _matched[str(script_directory())] = digest(local)
    return local, remote


def observe():
    local, remote = initialize()
    if remote is not None and local != remote:
        _matched[str(script_directory())] = None
    return local, remote


def auto_publish():
    local, remote = initialize()
    if remote is None or local == remote:
        atomic_write(state_path(), dict(read_object(state_path()), baseline=digest(local)))
        return True
    baseline = _matched.get(str(script_directory()))
    if baseline and digest(remote) == baseline:
        # The editor changed local scripts after a previously matching snapshot.
        if digest(read_backup()) != baseline:
            return False
        write_backup(local)
        atomic_write(state_path(), dict(read_object(state_path()), baseline=digest(local)))
        _matched[str(script_directory())] = digest(local)
        return True
    return False


def apply_selection(files, expected_local, expected_remote):
    validate(files)
    local = snapshot(script_directory())
    remote = read_backup()
    if remote is None or digest(local) != expected_local or digest(remote) != expected_remote:
        raise ValueError('Scripts changed while the comparison was open; reopen it.')
    from .script_updates import replace_script, recycle_script
    root = script_directory()
    try:
        for name in sorted(set(local) | set(files)):
            path = root / name
            if name not in files:
                recycle_script(path, root)
            elif name not in local:
                path.write_text(files[name]['source'], encoding='utf-8')
            elif files[name] != local[name]:
                replace_script(path, files[name]['source'], local[name]['source'], root)
        latest = read_backup()
        if latest is None or digest(latest) != expected_remote:
            raise ValueError('Backup changed; reopen the comparison.')
        write_backup(files)
    except Exception:
        # Restore the pre-dialog local contents if a write or final check failed.
        for name in set(local) | set(files):
            path = root / name
            if name in local:
                path.write_text(local[name]['source'], encoding='utf-8')
            else:
                path.unlink(missing_ok=True)
        raise
    # No filesystem extraction from archive names; validation permits basenames only.
    state = read_object(state_path())
    excluded = set(state.get('excluded', [])) | (set(local) - set(files))
    excluded -= set(files)
    atomic_write(state_path(), {'baseline': digest(files), 'excluded': sorted(excluded)})
    _matched[str(script_directory())] = digest(files)
