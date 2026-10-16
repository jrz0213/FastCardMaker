"""Durable returned results; credentials and media bytes are never stored here."""

import json
import sqlite3
import uuid
from contextlib import closing
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit
import re

from aqt import mw


class ResultCache:
    def __init__(self, directory=None):
        root = Path(directory or mw.pm.profileFolder())
        self.legacy_path = root / 'fastwq-pending.sqlite'
        self.path = root / 'fastcm-pending.sqlite'

    def existing_paths(self):
        return [path for path in (self.path, self.legacy_path) if path.is_file()]

    def put(self, snapshot, kind, payload, settings):
        if not snapshot.id:
            return None
        def mapping(value):
            allowed = {'fld_name', 'fld_ord', 'word_checked', 'dict_unique', 'dict_name',
                       'dict_fld_name', 'dict_fld_ord', 'ai_prompt', 'ignore', 'skip_valued', 'cloze_word'}
            return {key: item for key, item in value.items() if key in allowed}
        def result(value):
            return {key: value[key] for key in ('result', 'js', 'jsfile') if key in value}
        payload = dict(payload)
        if kind == 'ai':
            payload['tasks'] = [[task[0], task[1], mapping(task[2]), {}, task[4]] for task in payload['tasks']]
            payload['result'] = ({name: result(value) for name, value in payload['result'].items()}
                                 if payload['merged'] else result(payload['result']))
        else:
            payload['results'] = {target: result(value) for target, value in payload['results'].items()}
        record = {'nid': int(snapshot.id), 'original': list(snapshot.original),
                  'model': snapshot.model, 'mappings': [mapping(item) for item in snapshot._query_mappings],
                  'settings': {name: getattr(settings, name) for name in ('force_update', 'ignore_accents', 'cloze_str')},
                  'kind': kind, 'payload': payload}
        key = uuid.uuid4().hex
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as database:
            database.execute('PRAGMA synchronous=FULL')
            database.execute('CREATE TABLE IF NOT EXISTS results (id TEXT PRIMARY KEY, data TEXT NOT NULL)')
            with database:
                database.execute('INSERT INTO results VALUES (?, ?)',
                                 (key, json.dumps(record, ensure_ascii=False)))
        return key

    def read(self):
        records = {}
        for path in self.existing_paths():
            with closing(sqlite3.connect(path)) as database:
                if not database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='results'").fetchone():
                    continue
                for key, data in database.execute('SELECT id, data FROM results ORDER BY rowid'):
                    if key not in records:
                        records[key] = json.loads(data)
        return list(records.items())

    def remove(self, keys):
        if not keys:
            return
        keys = list(keys)
        for path in self.existing_paths():
            with closing(sqlite3.connect(path)) as database:
                if database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='results'").fetchone():
                    with database:
                        database.executemany('DELETE FROM results WHERE id = ?', [(key,) for key in keys])

    def pending(self):
        for path in self.existing_paths():
            with closing(sqlite3.connect(path)) as database:
                if database.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='results'").fetchone():
                    if database.execute('SELECT 1 FROM results LIMIT 1').fetchone() is not None:
                        return True
        return False


def missing_media(result, directory):
    """Only check local media references, leaving remote resources untouched."""
    references = re.findall(r'\[sound:([^\]]+)\]', result.get('result', ''))

    class MediaParser(HTMLParser):
        def handle_starttag(self, tag, attributes):
            if tag in ('img', 'audio', 'video', 'source', 'script'):
                references.extend(value for name, value in attributes if name == 'src' and value)

    MediaParser().feed(result.get('result', ''))
    files = result.get('jsfile') or []
    references.extend([files] if isinstance(files, str) else files)
    root = Path(directory).resolve()
    missing = []
    for reference in references:
        parts = urlsplit(reference)
        if parts.scheme or parts.netloc or reference.startswith('#'):
            continue
        name = unquote(parts.path)
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            missing.append(reference)
    return missing
