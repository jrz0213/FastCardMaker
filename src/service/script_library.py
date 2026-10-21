"""Portable script snapshots stored with shared settings, not machine paths."""
import ast
from copy import deepcopy
from pathlib import Path
import re
import tokenize

from .dictionary_binding import portable_source, source_binding


def script_directory():
    from ..utils.media import media_directory
    return Path(media_directory()).parent / 'fastcm' / 'scripts'


def install_library(library):
    """Explicit media-to-local synchronization replaces the local script cache."""
    validate(library)
    root = script_directory()
    root.mkdir(parents=True, exist_ok=True)
    from .script_updates import replace_script
    for name, item in library.items():
        path = root / name
        if path.exists():
            old = path.read_text(encoding='utf-8')
            if old != item['source']:
                replace_script(path, item['source'], old, root)
        else:
            path.write_text(item['source'], encoding='utf-8')


def snapshot(directory):
    result = {}
    for path in Path(directory).glob('*.py'):
        if path.name == '__init__.py' or not re.fullmatch(r'[\w -]+\.py', path.name):
            continue
        with tokenize.open(path) as stream:
            source = stream.read(500001)
        if len(source) > 500000:
            raise ValueError('Dictionary script is too large')
        result[path.name] = {'source': portable_source(source)}
    return result


def validate(library):
    if not isinstance(library, dict) or len(library) > 1024:
        raise ValueError('Invalid script library')
    for name, item in library.items():
        if not re.fullmatch(r'[\w -]+\.py', name) or name == '__init__.py':
            raise ValueError('Invalid dictionary script name')
        source = item.get('source') if isinstance(item, dict) else None
        if not isinstance(source, str) or len(source) > 500000:
            raise ValueError('Invalid dictionary script')
        ast.parse(source)


def publish(directory, javascript=None, dict_path=None):
    from .script_backup import auto_publish
    return auto_publish()


def migrate_configuration(data, aliases):
    data = deepcopy(data)
    def visit(value):
        if isinstance(value, dict):
            if value.get('dict_unique') in aliases:
                value['dict_unique'] = aliases[value['dict_unique']]
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(data)
    for old, new in aliases.items():
        if old in data.get('dicts', {}) and new not in data['dicts']:
            data['dicts'][new] = deepcopy(data['dicts'][old])
    return data
