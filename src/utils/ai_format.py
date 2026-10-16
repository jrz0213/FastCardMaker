"""Opt-in AI styles, limited to the AI output container."""

from copy import deepcopy
from hashlib import sha256
from html import escape
import re

from .markdown import markdown_to_html
from ..translations import text as tr

START = '/* FastCM AI styles: begin */'
END = '/* FastCM AI styles: end */'
_MARKED = r'/\* (?P<brand>FastCM|FastWQ) AI styles: begin \*/.*?/\* (?P=brand) AI styles: end \*/'
MANAGED = re.compile(_MARKED, re.S)
OWNED_BLOCK = re.compile(r'(?:\n\n)?' + _MARKED, re.S)
TAG_CLASSES = {'p': 'fwq-paragraph', 'table': 'fwq-table', 'ul': 'fwq-list',
               'ol': 'fwq-list', 'blockquote': 'fwq-quote', 'pre': 'fwq-code',
               'code': 'fwq-code', 'a': 'fwq-link', 'strong': 'fwq-emphasis',
               'em': 'fwq-emphasis', 'hr': 'fwq-rule',
               **{f'h{i}': 'fwq-heading' for i in range(1, 7)}}
DEFAULT_CSS = '''.fwq-ai { line-height: 1.6; text-align: left; overflow-wrap: anywhere; }
.fwq-ai .fwq-heading { margin: 0.8em 0 0.4em; }
.fwq-ai .fwq-paragraph { margin: 0.5em 0; }
.fwq-ai .fwq-table { border-collapse: separate; border-spacing: 0; width: 100%; margin: 0.8em 0; border: 1px solid rgba(128,128,128,0.35); border-radius: 8px; overflow: hidden; font-size: 0.95em; }
.fwq-ai .fwq-table th, .fwq-ai .fwq-table td { padding: 0.65em 0.85em; text-align: left; vertical-align: top; border-bottom: 1px solid rgba(128,128,128,0.25); }
.fwq-ai .fwq-table th { background: rgba(128,128,128,0.16); font-weight: 600; }
.fwq-ai .fwq-table tbody tr:nth-child(even) td { background: rgba(128,128,128,0.06); }
.fwq-ai .fwq-table tbody tr:last-child td { border-bottom: 0; }
.fwq-ai .fwq-list { padding-left: 1.5em; }
.fwq-ai .fwq-quote { border-left: 3px solid currentColor; margin: 0.6em 0; padding-left: 0.8em; opacity: 0.85; }
.fwq-ai .fwq-code { font-family: monospace; white-space: pre-wrap; }
.fwq-ai .fwq-link { text-decoration: underline; }
.fwq-ai .fwq-emphasis { color: inherit; }
.fwq-ai .fwq-rule { border: 0; border-top: 1px solid currentColor; }'''


def style_for(settings, model_id):
    styles = getattr(settings, 'ai_styles', {})
    value = styles.get(str(model_id), {}) if isinstance(styles, dict) else {}
    value = value if isinstance(value, dict) else {}
    return {**value, 'enabled': bool(getattr(settings, 'ai_css_enabled', False)) and value.get('enabled', True)}


def global_css(settings):
    value = getattr(settings, 'ai_css', None)
    if isinstance(value, str):
        return value
    # Preserve an older custom style as the initial shared style.
    styles = getattr(settings, 'ai_styles', {})
    if isinstance(styles, dict):
        for entry in styles.values():
            if isinstance(entry, dict) and isinstance(entry.get('css'), str):
                return entry['css']
    return DEFAULT_CSS


def render(text, markdown=True, classes=False):
    html = markdown_to_html(text) if markdown else escape(str(text)).replace('\n', '<br>')
    if not classes:
        return html
    # The renderer creates these tags itself and escapes all raw HTML.
    def add(match):
        tag = match.group(1)
        return '<' + tag + ' class="' + TAG_CLASSES[tag] + '"'
    html = re.sub(r'<(' + '|'.join(TAG_CLASSES) + r')(?=[\s>])', add, html)
    return '<div class="fwq-ai">' + html + '</div>'


def rules(css):
    """Simple flat rules only; selectors must remain inside .fwq-ai."""
    clean = re.sub(r'/\*.*?\*/', '', css, flags=re.S).strip()
    result = []
    position = 0
    for match in re.finditer(r'([^{}]+)\{([^{}]*)\}', clean):
        if clean[position:match.start()].strip():
            raise ValueError(tr('CSS 格式无效，请使用简单的 .fwq-ai 样式规则。'))
        selectors = [s.strip() for s in match.group(1).split(',')]
        if any(not re.match(r'^\.fwq-ai(?=[\s.:#\[>+~]|$)', s) for s in selectors):
            raise ValueError(tr('CSS 选择器必须以 .fwq-ai 开头。'))
        if any(re.search(r'[+~]', s) for s in selectors):
            raise ValueError(tr('CSS 不支持选择 AI 容器外的元素。'))
        result.append((selectors, match.group(2).strip()))
        position = match.end()
    if clean[position:].strip():
        raise ValueError(tr('CSS 格式无效，请使用简单的 .fwq-ai 样式规则。'))
    return result


def selectors_in(css):
    # Search selector positions only: comments and declaration values do not count.
    clean = re.sub(r'/\*.*?\*/', '', css, flags=re.S)
    return [s.strip() for m in re.finditer(r'(?:^|(?<=[{}]))([^{}]*)\{', clean)
            for s in m.group(1).split(',') if not s.lstrip().startswith('@')]


def inject_css(existing, desired, replace=False):
    parsed = rules(desired)
    base = OWNED_BLOCK.sub('', existing) if replace else existing
    owned = MANAGED.search(base)
    existing_selectors = selectors_in(owned.group(0)) if owned else []
    present = set(re.findall(r'\.([a-zA-Z_][\w-]*)', '\n'.join(existing_selectors)))
    additions = []
    for selectors, body in parsed:
        missing = []
        for selector in selectors:
            names = re.findall(r'\.([a-zA-Z_][\w-]*)', selector)
            key = names[-1]
            if key not in present:
                missing.append(selector)
        if missing:
            additions.append(', '.join(missing) + ' { ' + body + ' }')
    if not additions:
        return base
    block = '\n'.join(additions)
    if owned:
        position = owned.end() - len(END)
        return base[:position] + block + '\n' + base[position:]
    return base + '\n\n' + START + '\n' + block + '\n' + END


def save_style(models, model_id, css, enabled, replace=False):
    model = models.get(model_id)
    if not model:
        raise ValueError(tr('笔记类型不存在，请重新打开设置。'))
    old = model.get('css', '')
    new = inject_css(old, css, replace) if enabled else OWNED_BLOCK.sub('', old)
    if new == old:
        return None
    updated = deepcopy(model)
    updated['css'] = new
    updater = getattr(models, 'update_dict', None)
    return updater(updated) if callable(updater) else models.save(updated)


def apply_written_style(models, model_id, settings):
    """Called only after a real note commit, never by the settings dialog."""
    if not style_for(settings, model_id).get('enabled'):
        return None
    model = models.get(model_id)
    if not model:
        raise ValueError(tr('笔记类型不存在，请重新打开设置。'))
    desired = global_css(settings)
    stamp = '/* FastCM AI source: %s */' % sha256(desired.encode('utf-8')).hexdigest()
    old = model.get('css', '')
    owned = MANAGED.search(old)
    replace = bool(owned and stamp not in owned.group(0))
    new = inject_css(old, desired, replace=replace)
    if MANAGED.search(new) and stamp not in MANAGED.search(new).group(0):
        new = new.replace(START, START + '\n' + stamp, 1)
    if new == old:
        return None
    updated = deepcopy(model)
    updated['css'] = new
    updater = getattr(models, 'update_dict', None)
    return updater(updated) if callable(updater) else models.save(updated)
