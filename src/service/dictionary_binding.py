"""Portable MDX identity. Only the local catalogue contains absolute paths."""
import ast
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from hashlib import sha256
from html import unescape
import json
import os
from pathlib import Path
import re
import struct
import unicodedata
import zlib

_catalogue = ContextVar('fastcm_dictionary_catalogue', default=None)


def _normal(value):
    return unicodedata.normalize('NFC', value).strip()


@lru_cache(maxsize=512)
def _title(path, size, modified):
    with open(path, 'rb') as stream:
        length = struct.unpack('>I', stream.read(4))[0]
        if not 2 <= length <= 4 * 1024 * 1024:
            raise ValueError('Invalid MDX header size')
        data = stream.read(length)
        checksum = struct.unpack('<I', stream.read(4))[0]
    if len(data) != length or zlib.adler32(data) & 0xffffffff != checksum:
        raise ValueError('Invalid MDX header checksum')
    header = data.decode('utf-16').rstrip('\0')
    match = re.search(r'\bTitle\s*=\s*([\'\"])(.*?)\1', header, re.S)
    return _normal(unescape(match.group(2))) if match else ''


def descriptor(path):
    path = str(path)
    title = ''
    try:
        stat = os.stat(path)
        title = _title(os.path.realpath(path), stat.st_size, stat.st_mtime_ns)
    except (OSError, ValueError, UnicodeError, struct.error):
        pass
    return {'file': _normal(Path(path.replace('\\', '/')).stem), 'title': title}


def identity(binding):
    pair = [binding['file'].casefold(), binding['title']]
    return sha256(json.dumps(pair, ensure_ascii=False).encode('utf-8')).hexdigest()[:12]


class Catalogue:
    def __init__(self, folders, cancelled=None):
        self.files = {}
        seen = set()
        for folder in folders:
            for root, _, names in os.walk(folder):
                if cancelled and cancelled():
                    raise InterruptedError('Dictionary scan cancelled')
                for name in names:
                    if name.lower().endswith('.mdx'):
                        path = os.path.realpath(os.path.join(root, name))
                        key = os.path.normcase(path)
                        if key not in seen:
                            seen.add(key)
                            self.files.setdefault(_normal(Path(name).stem).casefold(), []).append(path)

    def candidates(self, binding):
        # Read headers only after the filename has matched.
        candidates = self.files.get(_normal(binding['file']).casefold(), [])
        return [path for path in candidates if not binding.get('title') or descriptor(path)['title'] == binding['title']]


@contextmanager
def use_catalogue(catalogue):
    token = _catalogue.set(catalogue)
    try:
        yield
    finally:
        _catalogue.reset(token)


def resolve_dictionary(filename, title='', legacy_path=''):
    catalogue = _catalogue.get()
    if catalogue is None:
        from ..context import config
        catalogue = Catalogue(getattr(config, 'dirs', []))
    binding = {'file': _normal(Path(filename.replace('\\', '/')).stem), 'title': _normal(title)}
    found = catalogue.candidates(binding)
    if len(found) == 1:
        return found[0]
    if legacy_path and os.path.isfile(legacy_path):
        candidate = os.path.realpath(legacy_path)
        if not found or candidate in found:
            return candidate
    from ..utils.logger import logger
    logger.warning('Dictionary unavailable: file=%s title=%s matches=%s', binding['file'], binding['title'], len(found))
    # Nonempty prevents legacy scripts from using a fuzzy fallback on failure.
    return '__fastcm_unavailable__/' + identity(binding) + '.mdx'


def source_binding(source):
    values = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ('DICT_FILE', 'DICT_TITLE', 'DICT_PATH'):
                    try:
                        values[target.id] = ast.literal_eval(node.value)
                    except (ValueError, TypeError):
                        pass
    if isinstance(values.get('DICT_FILE'), str):
        return {'file': Path(values['DICT_FILE'].replace('\\', '/')).stem, 'title': values.get('DICT_TITLE', '') or ''}
    if isinstance(values.get('DICT_PATH'), str) and values['DICT_PATH']:
        return {'file': descriptor(values['DICT_PATH'])['file'], 'title': ''}
    return None


def portable_source(source, path=None):
    """Replace legacy path constants without changing exports or class IDs."""
    # Runtime loading and backups preserve existing Python, including path repair code.
    # Explicit conversion is reserved for the user's import/association operation.
    if path is None:
        return source
    binding = descriptor(path)
    if not binding:
        return source
    tree = ast.parse(source)
    declarations = [node for node in tree.body if isinstance(node, ast.Assign) and any(
        isinstance(t, ast.Name) and t.id in ('DICT_PATH', 'DICT_FILE', 'DICT_TITLE') for t in node.targets)]
    declarations += [node for node in tree.body if isinstance(node, ast.ImportFrom) and
                     node.module == 'dictionary_binding' and node.level == 2 and
                     len(node.names) == 1 and node.names[0].name == 'resolve_dictionary']
    if not declarations:
        return source
    lines = source.splitlines(keepends=True)
    replacement = ('from ..dictionary_binding import resolve_dictionary\n'
                   'DICT_FILE = ' + repr(binding['file']) + '\n'
                   'DICT_TITLE = ' + repr('') + '\n'
                   'DICT_PATH = resolve_dictionary(DICT_FILE, DICT_TITLE)\n')
    first = min(node.lineno for node in declarations)
    for node in sorted(declarations, key=lambda n: n.lineno, reverse=True):
        lines[node.lineno - 1:node.end_lineno] = [replacement if node.lineno == first else '']
    result = ''.join(lines)
    compile(result, '<portable dictionary>', 'exec')
    return result
