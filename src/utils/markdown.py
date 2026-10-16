"""Minimal Markdown rendering for Anki fields; no CSS, scripts, or raw HTML."""

import re
from html import escape
from urllib.parse import urlsplit


def inline(text):
    parts = re.split(r'(`[^`\n]+`)', text)
    output = []
    for part in parts:
        if part.startswith('`') and part.endswith('`'):
            output.append('<code>' + escape(part[1:-1]) + '</code>')
            continue
        part = escape(part)
        def link(match):
            url = match.group(2)
            try:
                scheme = urlsplit(url).scheme.lower()
            except ValueError:
                return match.group(1)
            if scheme not in ('http', 'https', 'mailto'):
                return match.group(1)
            return '<a href="' + url + '">' + match.group(1) + '</a>'
        part = re.sub(r'(?<!!)\[([^\]]+)\]\(([^\s)]+)\)', link, part)
        part = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', part)
        part = re.sub(r'(?<!\*)\*([^*]+)\*(?!\*)', r'<em>\1</em>', part)
        output.append(part)
    return ''.join(output)


def markdown_to_html(text):
    lines = str(text).replace('\r\n', '\n').replace('\r', '\n').strip().split('\n')
    blocks, paragraph = [], []
    def flush():
        if paragraph:
            blocks.append('<p>' + '<br>'.join(inline(line) for line in paragraph) + '</p>')
            paragraph.clear()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('```'):
            flush()
            code = []
            i += 1
            while i < len(lines) and not lines[i].startswith('```'):
                code.append(lines[i])
                i += 1
            blocks.append('<pre><code>' + escape('\n'.join(code)) + '</code></pre>')
        elif not line.strip():
            flush()
        elif re.match(r'^#{1,6}\s', line):
            flush()
            marks, title = line.split(' ', 1)
            level = min(len(marks), 6)
            blocks.append('<h%d>%s</h%d>' % (level, inline(title), level))
        elif re.fullmatch(r'\s*[-*_]{3,}\s*', line):
            flush()
            blocks.append('<hr>')
        elif re.match(r'^\s*(?:[-*+] |\d+[.)] )', line):
            flush()
            ordered = bool(re.match(r'^\s*\d', line))
            pattern = r'^\s*\d+[.)]\s+(.+)' if ordered else r'^\s*[-*+]\s+(.+)'
            items = []
            while i < len(lines) and re.match(pattern, lines[i]):
                items.append('<li>' + inline(re.match(pattern, lines[i]).group(1)) + '</li>')
                i += 1
            tag = 'ol' if ordered else 'ul'
            blocks.append('<' + tag + '>' + ''.join(items) + '</' + tag + '>')
            continue
        elif line.startswith('>'):
            flush()
            quote = []
            while i < len(lines) and lines[i].startswith('>'):
                quote.append(inline(lines[i][1:].lstrip()))
                i += 1
            blocks.append('<blockquote>' + '<br>'.join(quote) + '</blockquote>')
            continue
        elif i + 1 < len(lines) and '|' in line and re.fullmatch(r'\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*', lines[i + 1]):
            flush()
            cells = lambda value: value.strip().strip('|').split('|')
            header = '<tr>' + ''.join('<th>' + inline(cell.strip()) + '</th>' for cell in cells(line)) + '</tr>'
            rows = []
            i += 2
            while i < len(lines) and '|' in lines[i] and lines[i].strip():
                rows.append('<tr>' + ''.join('<td>' + inline(cell.strip()) + '</td>' for cell in cells(lines[i])) + '</tr>')
                i += 1
            blocks.append('<table><thead>' + header + '</thead><tbody>' + ''.join(rows) + '</tbody></table>')
            continue
        else:
            paragraph.append(line)
        i += 1
    flush()
    return ''.join(blocks)
