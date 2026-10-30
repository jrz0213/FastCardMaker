"""Build an Anki add-on from tracked source files, never a live profile."""
import argparse
import ast
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
BLOCKED = {'__pycache__', 'user_files', '.fwq-history', '.fwq-trash', 'conversations', 'raw_replies'}


def build(destination):
    tracked = subprocess.check_output(['git', 'ls-files', '-z', '--', 'src'], cwd=ROOT).decode('utf-8').split('\0')
    entries = []
    for relative in filter(None, tracked):
        name = PurePosixPath(relative).relative_to('src')
        if BLOCKED.intersection(name.parts) or name.suffix in ('.pyc', '.log', '.sqlite', '.db') or name.name in ('meta.json', 'config.json'):
            raise ValueError('Private/runtime file is tracked: ' + relative)
        if name.parts[:2] == ('service', 'ai') and name.name != '.gitkeep':
            raise ValueError('AI runtime settings must not be packaged')
        path = ROOT / relative
        if path.suffix == '.py':
            ast.parse(path.read_text(encoding='utf-8-sig'), filename=relative)
        entries.append((name.as_posix(), path.read_bytes()))
    names = {name for name, _ in entries}
    required = {'__init__.py', 'gui/deck_creator.py', 'gui/note_creation.py', 'service/ai_support/streaming.py', 'locales/en.json', 'locales/ja.json'}
    if not required <= names:
        raise ValueError('Required modules missing: ' + repr(sorted(required - names)))
    if 'manifest.json' not in names:
        entries.append(('manifest.json', json.dumps({'package': '962326418', 'name': 'FastCard Maker'}, indent=2).encode('utf-8')))
    entries.append(('LICENSE', (ROOT / 'LICENSE').read_bytes()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(destination, 'w', ZIP_DEFLATED) as archive:
        for name, content in sorted(entries):
            archive.writestr(name, content)
    with ZipFile(destination) as archive:
        if archive.testzip() is not None:
            raise ValueError('Archive integrity check failed')
        json.loads(archive.read('manifest.json'))
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    destination.with_suffix(destination.suffix + '.sha256').write_text(digest + '  ' + destination.name + '\n', encoding='utf-8')
    print(json.dumps({'file': str(destination), 'files': len(entries), 'bytes': destination.stat().st_size, 'sha256': digest}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'dist' / 'FastCardMaker-2026.10.31.ankiaddon')
    build(parser.parse_args().output.resolve())
