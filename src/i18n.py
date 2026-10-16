"""UTF-8 catalogs; follow Anki's language, with safe English fallback."""

from contextlib import contextmanager
from functools import lru_cache
import json
from pathlib import Path
import re

LOCALES = Path(__file__).with_name('locales')
_override = None


def normalize(code):
    code = str(code or 'en').replace('_', '-')
    if code.lower() in ('zh', 'zh-cn', 'zh-hans'):
        return 'zh-CN'
    parts = code.split('-')
    if parts[0].lower() in ('en', 'ja'):
        return parts[0].lower()
    return parts[0].lower() + ('-' + parts[1].upper() if len(parts) > 1 else '')


def language():
    if _override:
        return normalize(_override)
    try:
        from .context import config
        configured = getattr(config, 'ui_language', '')
        if isinstance(configured, str) and configured:
            return normalize(configured)
    except (ImportError, AttributeError):
        pass
    try:
        from anki.lang import current_lang
        return normalize(current_lang() if callable(current_lang) else current_lang)
    except ImportError:
        return 'zh-CN'


@lru_cache(maxsize=32)
def catalog(code):
    code = normalize(code)
    if not re.fullmatch(r'[a-z]{2,3}(?:-[A-Z]{2})?', code):
        return {}
    try:
        data = json.loads((LOCALES / (code + '.json')).read_text(encoding='utf-8'))
        return {key: value for key, value in data.items() if isinstance(value, str)} if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return catalog(code.split('-')[0]) if '-' in code and code != 'zh-CN' else {}


def translate(key, fallback=None, locale=None):
    code = normalize(locale) if locale else language()
    values = catalog(code)
    if key in values:
        return values[key]
    if code == 'zh-CN':
        return fallback if fallback is not None else key
    return catalog('en').get(key, fallback if fallback is not None else key)


def languages():
    return [(path.stem, catalog(path.stem).get('_language_name', path.stem))
            for path in sorted(LOCALES.glob('*.json'))]


@contextmanager
def use_language(code):
    global _override
    previous, _override = _override, code
    try:
        yield
    finally:
        _override = previous
