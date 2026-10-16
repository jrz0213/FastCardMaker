"""Read dictionary-owned assets without executing JavaScript."""
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup
from ..translations import text as tr

JS_FILE_LIMIT = 30000
JS_TOTAL_LIMIT = 90000
JS_COUNT_LIMIT = 12


def local_key(value):
    value = unquote(value).replace('\\', '/')
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or '\x00' in value:
        raise ValueError('Not a dictionary resource')
    key = posixpath.normpath(parsed.path.lstrip('/'))
    if key in ('.', '..') or key.startswith('../'):
        raise ValueError('Resource outside dictionary')
    return key


def read_asset(builder, dict_path, key, limit=None):
    key = local_key(key)
    root = Path(dict_path).resolve().parent
    path = root.joinpath(*key.split('/')).resolve()
    try:
        path.relative_to(root)
        if path.is_file():
            with path.open('rb') as stream:
                return stream.read(limit) if limit else stream.read()
    except OSError:
        pass
    lookup = getattr(builder, 'mdd_lookup', None)
    values = lookup('\\' + key.replace('/', '\\'), ignorecase=True) if lookup else []
    if values and isinstance(values[0], bytes):
        return values[0][:limit] if limit else values[0]
    return None


def collect_javascript(samples, builder, dict_path, cancelled=None):
    """One shared bundle per dictionary; no remote requests or script execution."""
    assets, seen, queue = [], set(), []
    remaining = JS_TOTAL_LIMIT

    def add_inline(content):
        nonlocal remaining
        identity = ('inline', content)
        if identity in seen or not content.strip():
            return
        if len(assets) >= 48:
            return
        seen.add(identity)
        if len(assets) >= JS_COUNT_LIMIT or remaining <= 0:
            assets.append({'source': 'inline', 'status': 'omitted_limit'})
            return
        amount = min(JS_FILE_LIMIT, remaining)
        assets.append({'source': 'inline', 'content': content[:amount], 'truncated': len(content) > amount})
        remaining -= min(len(content), amount)

    for sample in samples:
        for script in BeautifulSoup(sample['html'], 'html.parser').find_all('script'):
            if len(queue) + len(assets) >= 48:
                break
            if script.get('src'):
                queue.append((str(script['src']), '', 0))
            else:
                add_inline(script.get_text())
    for reference, parent, depth in queue:
        if cancelled and cancelled():
            raise ValueError(tr('生成任务已取消。'))
        # Normalize only after joining relative imports; never fetch remote URLs.
        try:
            parsed = urlsplit(reference.replace('\\', '/'))
            if parsed.scheme or parsed.netloc:
                raise ValueError()
            key = local_key(posixpath.join(parent, reference) if not reference.startswith(('/', '\\')) else reference)
            if not key.lower().endswith(('.js', '.mjs')):
                raise ValueError()
        except ValueError:
            identity = ('excluded', reference)
            if identity not in seen:
                seen.add(identity)
                assets.append({'source': reference[:400], 'status': 'excluded_external_or_invalid'})
            continue
        if key in seen:
            continue
        seen.add(key)
        if len(seen) > 48:
            assets.append({'source': key, 'status': 'omitted_limit'})
            break
        if len([asset for asset in assets if 'content' in asset]) >= JS_COUNT_LIMIT or remaining <= 0:
            assets.append({'source': key, 'status': 'omitted_limit'})
            continue
        amount = min(JS_FILE_LIMIT, remaining)
        try:
            payload = read_asset(builder, dict_path, key, amount * 4 + 4)
        except ValueError:
            assets.append({'source': key, 'status': 'excluded_external_or_invalid'})
            continue
        if payload is None:
            assets.append({'source': key, 'status': 'missing'})
            continue
        content = payload.decode('utf-8-sig', 'replace')
        assets.append({'source': key, 'content': content[:amount], 'truncated': len(content) > amount})
        remaining -= min(len(content), amount)
        # Include bounded static module imports that can hold shared audio rules.
        if depth < 2:
            for match in re.finditer(r'(?:\bfrom\s*|\bimport\s*(?:\(\s*)?|\b(?:require|getScript|loadScript|include)\s*\(\s*)[\'"]([^\'"\n]+)[\'"]', content[:amount]):
                target = match.group(1)
                if target.startswith(('./', '../')) or target.lower().endswith(('.js', '.mjs')):
                    queue.append((target, posixpath.dirname(key), depth + 1))
    return assets
