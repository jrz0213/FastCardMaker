"""Cloze visible HTML text without reserializing tags or attributes."""

import re
from html.parser import HTMLParser


def cloze_html(html, word, stemmer, format_):
    term = stemmer.stemWord(word.replace('’', "'")).lower()

    def replace_text(text):
        pieces = re.split(r'(\{\{c\d+::.*?\}\})', text, flags=re.S)
        for index in range(0, len(pieces), 2):
            def replace(match):
                value = match.group(0)
                if stemmer.stemWord(value.replace('’', "'")).lower() != term:
                    return value
                length = len(word)
                if value[:length].lower() == word.lower():
                    return (format_ % value[:length]) + value[length:]
                return format_ % value
            pieces[index] = re.sub(r"\b[\w]+(?:['’\-][\w]+)*\b", replace, pieces[index])
        return ''.join(pieces)

    class TextNodes(HTMLParser):
        def __init__(self):
            super().__init__(convert_charrefs=False)
            self.hidden = []
            self.changes = []
            self.lines = [0]
            self.lines.extend(match.end() for match in re.finditer('\n', html))
            self.protected = [(match.start(), match.end())
                              for match in re.finditer(r'\{\{c\d+::.*?\}\}|\[sound:[^\]]+\]', html, flags=re.S)]

        def handle_starttag(self, tag, attrs):
            if tag in ('script', 'style'):
                self.hidden.append(tag)

        def handle_endtag(self, tag):
            if self.hidden and self.hidden[-1] == tag:
                self.hidden.pop()

        def handle_data(self, data):
            if not self.hidden:
                line, column = self.getpos()
                start = self.lines[line - 1] + column
                end = start + len(data)
                cursor = start
                parts = []
                for first, last in self.protected:
                    if last <= cursor or first >= end:
                        continue
                    first, last = max(first, cursor), min(last, end)
                    parts.append(replace_text(html[cursor:first]))
                    parts.append(html[first:last])
                    cursor = last
                parts.append(replace_text(html[cursor:end]))
                self.changes.append((start, end, ''.join(parts)))

    parser = TextNodes()
    parser.feed(html)
    parser.close()
    for start, end, value in reversed(parser.changes):
        html = html[:start] + value + html[end:]
    return html
