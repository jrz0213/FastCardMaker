"""Independent AI field queue, worker pool, progress, and main-thread writes."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
import time

from aqt.qt import QApplication, QMessageBox

from ..gui.ai_progress import AIProgressWindow
from ..service.ai import query_ai, query_ai_many, AIError
from ..service.ai_config import ai_send_rate, MAX_IN_FLIGHT, is_ai, profiles
from ..service.ai_validation import validate_ai_references
from ..utils.logger import logger
from ..translations import text as tr
from .common import inspect_note, cloze_deletion
from ..utils.media import profile_token
from ..context import config


@dataclass
class AIRequest:
    tasks: list
    merged: bool = False


def group_requests(tasks, send_mode=None):
    if not tasks:
        return []
    mode = send_mode or getattr(config, 'ai_send_mode', 'note')
    requests, groups = [], {}
    for task in tasks:
        unique = task[3]['dict_unique']
        if mode != 'note':
            requests.append(AIRequest([task]))
            continue
        key = (id(task[0]), unique)
        if key not in groups:
            groups[key] = AIRequest([], merged=True)
            requests.append(groups[key])
        groups[key].tasks.append(task)
    return requests


class AIQueryRunner:
    def __init__(self, notes, mappings=None, model=None, fields=None, flush=True, writer=None):
        self._profile_token = profile_token()
        self._pending = {}
        self.tasks = []
        self.model_ids = {}
        self.flush = flush
        self.writer = writer
        self.updated_fields = 0
        self.updated_notes = set()
        self.failed = 0
        self.cancelled = Event()
        self.validation_errors = []
        self.was_cancelled = False
        self.errors = {}
        for note in notes:
            if mappings is None:
                source, word, maps = inspect_note(note)
                note_model = note.note_type()
            else:
                maps, note_model = mappings, model
                source = next((i for i, item in enumerate(maps) if item.get('word_checked')), 0)
                word = None
            names = [item['name'] for item in note_model['flds']]
            self.model_ids[id(note)] = note_model.get('id')
            values = dict(zip(names, note.fields)) if hasattr(note, 'fields') else {name: note[name] for name in names}
            if word is None:
                source_name = maps[source].get('fld_name', names[0])
                word = values.get(source_name, '').strip()
            for index, mapping in enumerate(maps):
                target = mapping.get('fld_ord', index)
                if mapping.get('fld_name'):
                    if mapping['fld_name'] not in names:
                        logger.warning('Unavailable AI target skipped: %s', mapping['fld_name'])
                        continue
                    target = names.index(mapping['fld_name'])
                if index == source or mapping.get('ignore', False) or not is_ai(mapping.get('dict_unique')):
                    continue
                if not 0 <= target < len(names) or (fields is not None and target not in fields):
                    continue
                if mapping.get('skip_valued', False) and values[names[target]]:
                    continue
                try:
                    validate_ai_references(mapping.get('ai_prompt', ''), maps, names)
                except ValueError as error:
                    self.failed += 1
                    self.validation_errors.append(str(error))
                    continue
                self.tasks.append((note, names[target], target, dict(mapping), dict(values), word))
        self.requests = group_requests(self.tasks)
        self.total_requests = len(self.requests) + self.failed

    def apply(self, task, result):
        self.apply_many([task], {task[1]: result})

    def apply_many(self, tasks, results):
        """Prepare all values, then save the note once and roll back as a unit."""
        if self.cancelled.is_set() or self._profile_token != profile_token():
            return
        note = tasks[0][0]
        changes = []
        for _, name, index, mapping, _, word in tasks:
            content = results[name].get('result', '')
            if not content:
                continue
            if mapping.get('cloze_word') and word:
                content = cloze_deletion(content, word, getattr(self, 'query_settings', None))
            current = note.fields[index] if hasattr(note, 'fields') else note[name]
            if content != current:
                changes.append((name, index, current, content))
        if not changes:
            return

        def assign(name, index, value):
            if hasattr(note, 'fields'):
                note.fields[index] = value
            else:
                note[name] = value

        try:
            for name, index, _, content in changes:
                assign(name, index, content)
            if self.flush:
                if self.writer:
                    self.writer(note)
                else:
                    try:
                        note.col.update_note(note)
                    except AttributeError:
                        note.flush()
        except Exception:
            for name, index, current, _ in changes:
                assign(name, index, current)
            raise
        self.updated_fields += len(changes)
        self.updated_notes.add(id(note))

    def run(self, parent=None, progress=None, on_tick=None, report=True):
        if not self.requests:
            if progress:
                progress.update(self.failed, self.failed)
                progress.finish()
            if report:
                self.show_failures(parent)
            return
        rate = ai_send_rate()
        threads = min(MAX_IN_FLIGHT, len(self.requests))
        progress = progress or AIProgressWindow(self.total_requests, rate, parent)
        executor = ThreadPoolExecutor(max_workers=threads)
        pending = {}
        self._pending = pending
        remaining = iter(self.requests)
        completed = self.failed
        progress.update(completed, self.failed)
        started = time.monotonic()
        logger.info('[AI] batch start requests=%s requests_per_minute=%s workers=%s validation_failed=%s',
                    len(self.requests), rate, threads, self.failed)
        def submit():
            request = next(remaining, None)
            if request is not None:
                task = request.tasks[0]
                mapping, values = task[3], task[4]
                template = ({task[1]: task[3].get('ai_prompt', '') for task in request.tasks}
                            if request.merged else mapping.get('ai_prompt', ''))
                from ..service.ai import snapshot_connection
                connection = snapshot_connection(mapping['dict_unique'], self.model_ids[id(task[0])])
                future = executor.submit(query_ai_many if request.merged else query_ai,
                                         mapping['dict_unique'], template,
                                         values, cancelled=self.cancelled.is_set, connection=connection)
                pending[future] = request
        try:
            if progress.abort() or self._profile_token != profile_token():
                self.was_cancelled = True
                self.cancelled.set()
            else:
                for _ in range(threads):
                    submit()
            while pending:
                QApplication.processEvents()
                if on_tick:
                    on_tick()
                if progress.abort() or self._profile_token != profile_token():
                    self.was_cancelled = True
                    self.cancelled.set()
                finished = [future for future in pending if future.done()]
                for future in finished:
                    request = pending.pop(future)
                    completed += 1
                    if not self.cancelled.is_set():
                        try:
                            result = future.result()
                            try:
                                if request.merged:
                                    self.apply_many(request.tasks, result)
                                else:
                                    self.apply(request.tasks[0], result)
                            except Exception:
                                raise AIError(tr('字段保存失败，原内容已恢复。'), code='field_save') from None
                        except Exception as error:
                            self.failed += 1
                            message = str(error) if isinstance(error, AIError) else tr('请求执行失败，请查看日志中的错误类别。')
                            self.errors[message] = self.errors.get(message, 0) + 1
                            logger.error('[AI] field failed category=%s', getattr(error, 'code', type(error).__name__))
                    if not self.cancelled.is_set():
                        submit()
                progress.update(completed, self.failed)
                if not finished:
                    time.sleep(0.02)
        finally:
            self.cancelled.set()
            executor.shutdown(wait=True, cancel_futures=True)
            progress.finish()
            logger.info('[AI] batch complete updated_fields=%s failed=%s cancelled=%s duration=%.2fs',
                        self.updated_fields, self.failed, self.was_cancelled, time.monotonic() - started)
        if report:
            self.show_failures(parent)

    def cancel(self, wait=False):
        self.was_cancelled = True
        self.cancelled.set()
        if wait:
            while any(not future.done() for future in list(self._pending)):
                QApplication.processEvents()
                time.sleep(0.02)

    def show_failures(self, parent):
        if not self.failed:
            return
        reasons = dict(self.errors)
        for message in self.validation_errors:
            reasons[message] = reasons.get(message, 0) + 1
        lines = ['%s × %s' % (count, message) for message, count in list(reasons.items())[:5]]
        QMessageBox.warning(parent, tr('AI 查询失败汇总'),
                            tr('共 %s 项失败，原字段内容保留。\n\n%s') %
                            (self.failed, '\n'.join(lines)))


def dictionary_notes(notes, fields=None, mappings=None):
    result = []
    for note in notes:
        source, _, maps = inspect_note(note) if mappings is None else (
            next((i for i, item in enumerate(mappings) if item.get('word_checked')), 0), '', mappings)
        for index, item in enumerate(maps):
            target = item.get('fld_ord', index)
            if index == source or item.get('ignore', False) or not item.get('dict_unique') or is_ai(item['dict_unique']):
                continue
            if fields is None or target in fields:
                result.append(note)
                break
    return result
