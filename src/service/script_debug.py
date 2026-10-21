"""Run only verified generated export bodies, with temporary media output.

Module imports, original constructors and unrelated original methods are never
executed. This checks generated exports, not every behavior of a legacy script.
"""
import ast
from copy import copy, deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import inspect
from pathlib import Path
import tempfile
import time
import traceback
from urllib.parse import unquote, urlsplit
import uuid

from .selector_scripts import render_script, extract_required, resolve_entry, adapt_extracted
from .script_updates import update_source, dictionary_identity


def _exports(source):
    found = {}
    for cls in ast.parse(source).body:
        if not isinstance(cls, ast.ClassDef):
            continue
        for method in cls.body:
            if not isinstance(method, ast.FunctionDef):
                continue
            for decorator in method.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(decorator.func, ast.Name) and decorator.func.id == 'export' and decorator.args:
                    try:
                        labels = ast.literal_eval(decorator.args[0])
                    except (ValueError, TypeError):
                        continue
                    for label in labels if isinstance(labels, (list, tuple)) else [labels]:
                        found[(cls.name, label)] = method
    return found


def _function(actual, expected, rules, path):
    if ast.dump(ast.Module(body=actual.body, type_ignores=[])) != ast.dump(ast.Module(body=expected.body, type_ignores=[])):
        raise ValueError('Export body differs from the validated generated template')
    method = deepcopy(actual)
    method.decorator_list = []
    method.returns = None
    for arg in [*method.args.posonlyargs, *method.args.args, *method.args.kwonlyargs,
                *([method.args.vararg] if method.args.vararg else []),
                *([method.args.kwarg] if method.args.kwarg else [])]:
        arg.annotation = None
    for default in [*method.args.defaults, *method.args.kw_defaults]:
        if default is not None:
            ast.literal_eval(default)  # Reject executable defaults from old scripts.
    namespace = {'__builtins__': {}, 'RULES': rules['fields'], 'DICT_PATH': path,
                 'extract_required': extract_required, 'resolve_entry': resolve_entry,
                 'adapt_extracted': adapt_extracted, '_fwq_extract_required': extract_required,
                 '_fwq_resolve_entry': resolve_entry, '_fwq_adapt_extracted': adapt_extracted}
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    exec(compile(module, '<FastCM generated export>', 'exec'), namespace)
    return namespace[method.name]


def _missing_media(html, directory):
    import re
    references = re.findall(r'\[sound:([^\]]+)\]', html)
    class Media(HTMLParser):
        def handle_starttag(self, tag, attrs):
            if tag in ('img', 'audio', 'video', 'source', 'script', 'link'):
                references.extend(value for key, value in attrs if key in ('src', 'href') and value)
    Media().feed(html)
    missing = []
    for reference in references:
        parsed = urlsplit(reference)
        if parsed.scheme or parsed.netloc or reference.startswith('#'):
            continue
        target = (Path(directory) / unquote(parsed.path)).resolve()
        if not target.is_relative_to(Path(directory).resolve()) or not target.is_file():
            missing.append(reference)
    return list(dict.fromkeys(missing))


def _debug_exports(service, result, cancelled=None, class_name=None):
    started = time.monotonic()
    rules = result['rules']
    original = result.get('original')
    expected = update_source(original['source'], rules, class_name) if original else render_script(service.dict_path, rules)[1]
    actual, template = _exports(result['source']), _exports(expected)
    report = {'id': uuid.uuid4().hex, 'kind': 'debug', 'time': datetime.now(timezone.utc).isoformat(),
              'dictionary_id': dictionary_identity(service.dict_path), 'source_sha256': sha256(result['source'].encode()).hexdigest(),
              'scope': 'generated_exports_only', 'original_initialization': 'not_executed',
              'rows': [], 'files': [], 'passed': True, 'cancelled': False}
    with tempfile.TemporaryDirectory(prefix='fastcm-script-debug-') as temporary:
        instance = copy(service)
        instance.media_dir, instance._media_saved, instance._media_writing = temporary, {}, set()
        instance.missed_css = set()
        if rules.get('media'):
            from .mdx_media import MdxMediaMixin
            instance.__media_rules__ = rules['media']
            for sample in result['samples']:
                row = {'word': sample['word'], 'field': 'media', 'passed': False}
                try:
                    row['result'] = MdxMediaMixin.adapt_to_anki(instance, sample['html'])
                    missing = _missing_media(row['result'], temporary)
                    if missing:
                        raise FileNotFoundError('Missing repaired media: ' + ', '.join(missing))
                    row['passed'] = True
                except Exception as error:
                    row.update(error=str(error), error_type=type(error).__name__, traceback=traceback.format_exc())
                    report['passed'] = False
                report['rows'].append(row)
        for sample in result['samples']:
            for rule in rules['fields']:
                if cancelled and cancelled():
                    report['cancelled'], report['passed'] = True, False
                    break
                row = {'word': sample['word'], 'field': rule['name'], 'passed': False}
                try:
                    keys = [key for key in template if key[1] == rule['name'] and (not class_name or key[0] == class_name)]
                    if len(keys) != 1 or keys[0] not in actual:
                        raise ValueError('Cannot identify the generated exported method')
                    method = _function(actual[keys[0]], template[keys[0]], rules, service.dict_path)
                    instance._word = sample['word']
                    inspect.signature(method).bind(instance)
                    output = method(instance)
                    output = output.result if hasattr(output, 'result') else output
                    if not isinstance(output, str) or not output.strip():
                        raise ValueError('Generated field returned no text')
                    row['result'] = output
                    missing = _missing_media(output, temporary)
                    if missing:
                        raise FileNotFoundError('Missing exported media: ' + ', '.join(missing))
                    row['passed'] = True
                except Exception as error:
                    row.update(error_type=type(error).__name__, error=str(error), traceback=traceback.format_exc())
                    report['passed'] = False
                report['rows'].append(row)
            if report['cancelled']:
                break
        for path in sorted(Path(temporary).rglob('*')):
            if path.is_file():
                digest = sha256()
                with path.open('rb') as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                        digest.update(chunk)
                report['files'].append({'name': path.name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return report


def debug_exports(service, result, cancelled=None, class_name=None):
    try:
        if result.get('format') == 'python':
            return _debug_python(service, result, cancelled)
        return _debug_exports(service, result, cancelled, class_name)
    except Exception as error:
        return {'id': uuid.uuid4().hex, 'kind': 'debug', 'time': datetime.now(timezone.utc).isoformat(),
                'dictionary_id': dictionary_identity(service.dict_path), 'passed': False,
                'source_sha256': sha256(result.get('source', '').encode()).hexdigest(),
                'scope': 'complete_python_script' if result.get('format') == 'python' else 'generated_exports_only', 'error_type': type(error).__name__,
                'error': str(error), 'traceback': traceback.format_exc()}


def _debug_python(service, result, cancelled=None):
    """Explicit user-requested execution of a complete script. This is not a sandbox."""
    from .python_scripts import parse_python
    from .dictionary_binding import Catalogue, use_catalogue
    source, name = parse_python(result['source'], result.get('class_name'))
    report = {'id': uuid.uuid4().hex, 'kind': 'debug', 'time': datetime.now(timezone.utc).isoformat(),
              'dictionary_id': dictionary_identity(service.dict_path),
              'source_sha256': sha256(source.encode()).hexdigest(), 'scope': 'complete_python_script',
              'original_initialization': 'executed', 'rows': [], 'files': [], 'passed': True, 'cancelled': False}
    started = time.monotonic()
    namespace = {'__name__': __package__ + '.dict._fastcm_debug', '__package__': __package__ + '.dict'}
    with tempfile.TemporaryDirectory(prefix='fastcm-python-debug-') as temporary:
        with use_catalogue(Catalogue([str(Path(service.dict_path).parent)])):
            if cancelled and cancelled():
                report.update(cancelled=True, passed=False)
                return report
            exec(compile(source, '<AI dictionary debug>', 'exec'), namespace)
            instance = namespace[name]()
        instance.dict_path, instance.builder = service.dict_path, service.builder
        instance.media_dir, instance._media_saved, instance._media_writing = temporary, {}, set()
        instance.missed_css = set()
        for sample in result['samples']:
            instance.word = sample['word']
            for label, action in instance.exporters:
                if cancelled and cancelled():
                    report.update(cancelled=True, passed=False)
                    return report
                row = {'word': sample['word'], 'field': label, 'passed': False}
                try:
                    value = action()
                    value = getattr(value, 'result', value)
                    row['result'] = str(value)
                    missing = _missing_media(row['result'], temporary)
                    if missing:
                        raise FileNotFoundError('Missing media: ' + ', '.join(missing))
                    row['passed'] = True
                except Exception as error:
                    row.update(error=str(error), error_type=type(error).__name__, traceback=traceback.format_exc())
                    report['passed'] = False
                report['rows'].append(row)
        for path in sorted(Path(temporary).rglob('*')):
            if path.is_file():
                report['files'].append({'name': str(path.relative_to(temporary)), 'bytes': path.stat().st_size,
                                        'sha256': sha256(path.read_bytes()).hexdigest()})
    report['elapsed_seconds'] = round(time.monotonic() - started, 3)
    return report
