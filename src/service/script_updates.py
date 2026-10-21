"""Stable generated adapters and bounded edits to existing dictionary scripts."""
import ast
import os
import shutil
import tempfile
import importlib
import importlib.util
import tokenize
from hashlib import sha256
from pathlib import Path
from datetime import datetime, timezone, timedelta
from threading import Lock

from ..translations import text as tr

SCRIPT_LIMIT = 60000
_stamp_lock = Lock()
_last_stamp = None


def invalidate_script_cache(path):
    path = Path(path).resolve()
    cache = Path(importlib.util.cache_from_source(str(path)))
    if cache.parent.resolve() == (path.parent / '__pycache__').resolve():
        cache.unlink(missing_ok=True)
    importlib.invalidate_caches()


def timestamp():
    global _last_stamp
    with _stamp_lock:
        now = datetime.now(timezone.utc)
        if _last_stamp is not None and now <= _last_stamp:
            now = _last_stamp + timedelta(microseconds=1)
        _last_stamp = now
        return now.astimezone(timezone(timedelta(hours=8))).strftime('%Y%m%d_%H%M%S_%f')


def history_directory(directory):
    folder = Path(directory).resolve() / '.fwq-history'
    if folder.is_symlink():
        raise ValueError('Invalid history directory')
    return folder


def trash_directory(directory):
    folder = Path(directory).resolve() / '.fwq-trash'
    if folder.is_symlink():
        raise ValueError('Invalid recycle directory')
    return folder


def recycle_script(path, directory):
    path, root = Path(path).resolve(), Path(directory).resolve()
    if path.parent != root or path.suffix != '.py' or path.name == '__init__.py':
        raise ValueError('Invalid script target')
    folder = trash_directory(directory)
    folder.mkdir(parents=True, exist_ok=True)
    destination = folder / ('script_' + timestamp() + '_' + path.name + '.bak')
    shutil.copy2(path, destination)
    path.unlink()
    invalidate_script_cache(path)
    return str(destination)


def prune_old_scripts(directory, now=None):
    """Expire only timestamped recycled script versions, never active scripts."""
    now = now or datetime.now(timezone.utc)
    folder = trash_directory(directory)
    if not folder.exists() or folder.is_symlink() or folder.resolve().parent != Path(directory).resolve():
        return 0
    count = 0
    for path in folder.glob('script_*.bak'):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            archived = datetime.strptime(path.name[7:29], '%Y%m%d_%H%M%S_%f').replace(tzinfo=timezone(timedelta(hours=8)))
        except ValueError:
            continue
        if now - archived > timedelta(days=7):
            path.unlink()
            count += 1
    return count


def expire_for_plugin():
    try:
        return prune_old_scripts(Path(__file__).with_name('dict'))
    except (OSError, ValueError):
        return 0


def restore_script(backup, directory):
    backup, folder = Path(backup).resolve(), trash_directory(directory)
    if backup.parent != folder or not backup.name.startswith('script_') or not backup.name.endswith('.py.bak'):
        raise ValueError('Invalid recycled script')
    filename = backup.name[30:-4]
    if Path(filename).name != filename or not filename.endswith('.py'):
        raise ValueError('Invalid script filename')
    destination = Path(directory).resolve() / filename
    if destination.is_symlink():
        raise ValueError('Invalid restore target')
    with tokenize.open(backup) as stream:
        source = stream.read()
    compile(source, filename, 'exec')
    if destination.exists():
        # Restoring is reversible: put the currently active version in the bin first.
        shutil.copy2(destination, folder / ('script_' + timestamp() + '_' + filename + '.bak'))
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.fwq-restore-', suffix='.tmp', delete=False) as stream:
            temporary = stream.name
            stream.write(backup.read_bytes())
        os.replace(temporary, destination)
        temporary = None
        invalidate_script_cache(destination)
    finally:
        if temporary:
            os.remove(temporary)
    return str(destination)


def write_conversation(record, directory):
    import json
    folder = history_directory(directory)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / ('conversation_' + timestamp() + '.json')
    with path.open('x', encoding='utf-8') as stream:
        json.dump(record, stream, ensure_ascii=False, indent=2)
    return str(path)


def dictionary_identity(path):
    from .dictionary_binding import descriptor, identity
    return identity(descriptor(path))


def original_scripts(paths):
    originals, seen = [], set()
    for path in dict.fromkeys(paths):
        source_path = Path(path)
        identity = os.path.normcase(str(source_path.resolve()))
        if identity in seen:
            continue
        seen.add(identity)
        if source_path.suffix.lower() != '.py' or not source_path.is_file():
            continue
        with tokenize.open(source_path) as stream:
            source = stream.read(500001)
        if len(source) > 500000:
            raise ValueError(tr('原脚本过大，无法安全更新。'))
        originals.append({'path': str(source_path.resolve()), 'source': source})
    return originals


def script_payload(originals):
    from .dictionary_binding import portable_source
    return [{'name': Path(item['path']).name, 'source': portable_source(item['source'])[:SCRIPT_LIMIT],
             'truncated': len(item['source']) > SCRIPT_LIMIT} for item in originals[:4]]


def update_source(source, rules, class_name=None):
    """Only insert validated extraction rules; never run AI-written Python."""
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef) and any(
        isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == 'register'
        for deco in node.decorator_list)]
    if class_name:
        classes = [node for node in classes if node.name == class_name]
    if len(classes) != 1:
        raise ValueError(tr('原脚本的词典类无法确定，未修改脚本。'))
    cls = classes[0]
    exports = {}
    for method in cls.body:
        if not isinstance(method, ast.FunctionDef):
            continue
        for deco in method.decorator_list:
            if isinstance(deco, ast.Call) and isinstance(deco.func, ast.Name) and deco.func.id == 'export' and deco.args:
                try:
                    labels = ast.literal_eval(deco.args[0])
                except (ValueError, TypeError):
                    continue
                for label in labels if isinstance(labels, (list, tuple)) else [labels]:
                    if isinstance(label, str):
                        exports[label] = method
    lines = source.splitlines(keepends=True)
    changes, additions, replaced = [], [], set()
    if 'media' in rules:
        from .media_rules import validate_media
        validate_media(rules['media'])
        assignment = ' ' * (cls.col_offset + 4) + '__media_rules__ = ' + repr(rules['media']) + '\n'
        previous = [node for node in cls.body if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == '__media_rules__' for t in node.targets)]
        if previous:
            changes.append((previous[0].lineno - 1, previous[0].end_lineno, assignment))
        else:
            additions.append('\n' + assignment)
    known = {node.name for node in cls.body if isinstance(node, ast.FunctionDef)}
    for index, rule in enumerate(rules['fields']):
        method = exports.get(rule['name'])
        indent = ' ' * (cls.col_offset + 4)
        body_indent = indent + '    '
        body = (body_indent + 'rule = ' + repr(rule) + '\n' +
                body_indent + 'value = _fwq_extract_required(_fwq_resolve_entry(self.builder, self.word), rule, self.builder, self.dict_path)\n' +
                body_indent + 'return _fwq_adapt_extracted(self, value, rule)\n')
        if method is not None:
            if method.name in replaced:
                raise ValueError(tr('多个字段对应同一原方法，未修改脚本。'))
            replaced.add(method.name)
            header = indent + 'def ' + method.name + '(' + ast.unparse(method.args) + ')'
            if method.returns is not None:
                header += ' -> ' + ast.unparse(method.returns)
            changes.append((method.lineno - 1, method.end_lineno, header + ':\n' + body))
        else:
            name = 'fwq_generated_field_%02d' % index
            while name in known:
                name += '_'
            known.add(name)
            additions.append('\n' + indent + '@export(' + repr([rule['name'], rule['name']]) + ')\n' +
                             indent + 'def ' + name + '(self):\n' + body)
    if additions:
        changes.append((cls.end_lineno, cls.end_lineno, ''.join(additions)))
    imports = ('from ..selector_scripts import extract_required as _fwq_extract_required, '
               'resolve_entry as _fwq_resolve_entry, adapt_extracted as _fwq_adapt_extracted\n')
    if imports.strip() not in source:
        first = min([cls.lineno] + [deco.lineno for deco in cls.decorator_list]) - 1
        changes.append((first, first, imports + '\n'))
    for first, last, replacement in sorted(changes, key=lambda item: (item[0], item[1]), reverse=True):
        lines[first:last] = [replacement]
    result = ''.join(lines)
    compile(result, '<updated dictionary>', 'exec')
    return result


def replace_script(path, source, expected_source, directory):
    path, root = Path(path).resolve(), Path(directory).resolve()
    if path.parent != root or path.suffix.lower() != '.py':
        raise ValueError('Invalid script target')
    compile(source, str(path), 'exec')
    with tokenize.open(path) as stream:
        current, encoding = stream.read(), stream.encoding
    if current != expected_source:
        raise ValueError(tr('原脚本已被修改，请重新生成后保存。'))
    folder = trash_directory(directory)
    folder.mkdir(parents=True, exist_ok=True)
    backup = folder / ('script_' + timestamp() + '_' + path.name + '.bak')
    shutil.copy2(path, backup)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix='.fwq-script-', suffix='.tmp',
                                         mode='w', encoding=encoding, delete=False) as stream:
            temporary = stream.name
            stream.write(source)
        os.replace(temporary, path)
        temporary = None
        invalidate_script_cache(path)
    finally:
        if temporary:
            os.remove(temporary)
    return str(path)
