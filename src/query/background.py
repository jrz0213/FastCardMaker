"""Event-driven query jobs with frozen inputs and main-thread conflict checks."""

from concurrent.futures import ThreadPoolExecutor
from copy import copy, deepcopy
from collections import deque, Counter
import re
import time
import weakref
from types import SimpleNamespace

from aqt import mw
from aqt.qt import QObject, QTimer, QThread, QApplication, QWidget, QDialog, QMainWindow, Qt, pyqtSignal
from aqt.utils import tooltip

from .common import inspect_note, FieldResults
from .worker import QueryWorkerManager
from .ai_runner import AIQueryRunner, dictionary_notes
from .editor_bridge import EditorBarrier, matching_editors
from .result_cache import ResultCache, missing_media
from ..service import service_pool
from ..service.ai_config import MAX_IN_FLIGHT, ai_send_rate
from ..service.ai import AIError, snapshot_connection
from ..service.script_updates import expire_for_plugin
from ..context import config
from ..utils.media import profile_token
from ..utils.logger import logger
from ..utils.ai_format import global_css, apply_written_style
from ..translations import text as tr
from ..gui.query_progress import QueryProgressWindow
from ..gui.task_progress import progress_hub, ProgressReport

_jobs = []


def active_job():
    return next((job for job in _jobs if not job.done), None)


class NoteSnapshot:
    def __init__(self, note, mappings):
        self.live = note
        self.id = getattr(note, 'id', None)
        self.fields = list(note.fields)
        self.original = tuple(note.fields)
        self.model = deepcopy(note.note_type())
        self._query_mappings = deepcopy(mappings if mappings is not None else inspect_note(note)[2])

    def note_type(self):
        return self.model


class QueryJob(QObject):
    changed = pyqtSignal()
    finished = pyqtSignal()

    def __init__(self, notes, flush=True, fields=None, mappings=None, model=None,
                 writer=None, parent=None, on_complete=None, guard=None, editor=None, query_settings=None,
                 start_in_background=False):
        super().__init__()
        expire_for_plugin()
        self.token = profile_token()
        self.style_settings = SimpleNamespace(ai_css_enabled=bool(getattr(config, 'ai_css_enabled', False)),
                                             ai_styles=deepcopy(getattr(config, 'ai_styles', {})),
                                             ai_css=global_css(config))
        self.styled_types = set()
        self.flush, self.guard = flush, guard
        self.on_complete = on_complete
        self.parent_window = weakref.ref(parent) if isinstance(parent, QWidget) else lambda: None
        self.snapshots = [NoteSnapshot(note, mappings) for note in notes]
        query_settings = query_settings or SimpleNamespace(force_update=config.force_update,
                                        ignore_accents=config.ignore_accents,
                                        cloze_str=getattr(config, 'cloze_str', '{{c1::%s}}'))
        for snapshot in self.snapshots:
            snapshot._query_settings = query_settings
            snapshot.editor_ref = weakref.ref(editor) if editor is not None else None
        self.ai = AIQueryRunner(self.snapshots, mappings=mappings, model=model, fields=fields,
                                flush=flush, writer=writer)
        self.dictionary = QueryWorkerManager()
        self.dictionary.flush = flush
        self.original_writer = writer
        self.dictionary.writer = self.ai.writer = self.save_note
        self.dictionary.query_fields = fields
        self.dictionary.query_mappings = deepcopy(mappings)
        self.dictionary.query_settings = self.ai.query_settings = query_settings
        self.connections = {(task[3]['dict_unique'], task[0].model['id']):
                            snapshot_connection(task[3]['dict_unique'], task[0].model['id'])
                            for task in self.ai.tasks}
        self.dictionary.include_ai = False
        self.regular = dictionary_notes(self.snapshots, fields, mappings)
        for snapshot in self.regular:
            self.dictionary.queue.put(snapshot)
        self.window = QueryProgressWindow(len(self.regular), self.ai.total_requests, ai_send_rate(),
                                          mw if isinstance(mw, QWidget) else None, show_window=not start_in_background)
        self.dictionary.progress = self.window.dictionary
        self.window.background_requested.connect(self.background)
        self.dictionary.handle_result = self._dictionary_result
        self.done = self.cancelled = False
        self.is_background = start_in_background
        self.silent = False
        self.conflicts = self.completed_ai = self.completed_dictionary = 0
        self.notices = []
        self.total = len(self.regular) + self.ai.total_requests
        self.executor = None
        self.pending = {}
        self.write_queue = deque()
        self.result_queue = deque()
        self.dictionary_remaining = Counter(id(note) for note in self.regular)
        self.ai_remaining = Counter(id(request.tasks[0][0]) for request in self.ai.requests)
        self.write_interval = 30.0
        self.next_write_at = None
        self.round_keys = {}
        self.round_started_at = None
        self.save_seconds = self.cleanup_seconds = self.refresh_seconds = self.cache_wait_seconds = 0.0
        self.cache_wait_started_at = None
        self.unnotified_writes = False
        self.collecting = True
        self.staged_note = None
        self.staged_base = None
        self.staged_targets = set()
        self.saved_changes = None
        self.result_cache = ResultCache()
        self.cache_keys = {}
        self.cache_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='fwq-cache')
        self.cache_pending = {}
        self.cleanup_keys = []
        self.cleanup_future = None
        self.query_finished_at = self.cleanup_started_at = None
        self.save_total = self.save_completed = 0
        self.phase = 'query'
        self.writing = False
        self.writing_kind = None
        self.barrier = None
        self.editor_fields = []
        self.remaining = iter(self.ai.requests)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.tick)

    @property
    def completed(self):
        return self.completed_dictionary + self.completed_ai + len(self.ai.validation_errors)

    def save_note(self, note):
        if self.staged_note is not None:
            return None
        changes = self.original_writer(note) if self.original_writer else mw.col.update_note(note)
        self.unnotified_writes = True
        self.merge_changes(changes)
        return changes

    def merge_changes(self, changes):
        if hasattr(changes, 'note_text'):
            if self.saved_changes is None:
                self.saved_changes = changes
            else:
                # Operation flags are booleans: preserve all changes in one notification.
                for name in ('card', 'note', 'deck', 'tag', 'notetype', 'config', 'deck_config',
                             'mtime', 'browser_table', 'browser_sidebar', 'note_text', 'study_queues'):
                    if getattr(changes, name, False):
                        setattr(self.saved_changes, name, True)

    def notify_saved(self):
        if self.token != profile_token() or not self.flush or not self.unnotified_writes:
            return
        changes = self.saved_changes
        self.saved_changes = None
        self.unnotified_writes = False
        if hasattr(changes, 'note_text'):
            try:
                from aqt import gui_hooks
                notify = getattr(gui_hooks, 'operation_did_execute', None)
            except ImportError:
                notify = None
            if callable(notify):
                try:
                    notify(changes, self)
                    return
                except Exception as error:
                    # The database commit already succeeded; notification failure
                    # cannot be treated as a rolled-back note save.
                    logger.warning('Could not notify Anki of field updates: %s', type(error).__name__)
        reset = getattr(mw, 'reset', None)
        if callable(reset):
            try:
                reset()
            except Exception as error:
                self.notices.append(tr('字段已保存，但编辑器刷新失败，请重新打开笔记。'))
                logger.warning('Could not refresh Anki after batch: %s', type(error).__name__)

    @property
    def failed(self):
        return self.dictionary.fails + self.ai.failed

    def start(self):
        self.started_at = time.monotonic()
        self.next_write_at = self.started_at + self.write_interval
        _jobs.append(self)
        progress_hub().current = self
        progress_hub().started.emit(self)
        if self.regular:
            self.dictionary.start()
        if self.ai.requests:
            self.executor = ThreadPoolExecutor(max_workers=min(MAX_IN_FLIGHT, len(self.ai.requests)))
            for _ in range(min(MAX_IN_FLIGHT, len(self.ai.requests))):
                self.submit()
        self.timer.start()
        return self

    def submit(self):
        if self.ai.cancelled.is_set() or self.cancelled:
            return
        request = next(self.remaining, None)
        if request is None:
            return
        from . import ai_runner
        task = request.tasks[0]
        mapping, values = task[3], task[4]
        prompt = ({task[1]: task[3].get('ai_prompt', '') for task in request.tasks}
                  if request.merged else mapping.get('ai_prompt', ''))
        future = self.executor.submit(ai_runner.query_ai_many if request.merged else ai_runner.query_ai,
                                      mapping['dict_unique'], prompt, values,
                                      cancelled=self.ai.cancelled.is_set,
                                      connection=self.connections[(mapping['dict_unique'], task[0].model['id'])])
        self.pending[future] = request
        self.ai._pending = self.pending

    def current_note(self, snapshot, targets, dependencies):
        if self.token != profile_token() or self.cancelled or (self.guard and not self.guard()):
            return None
        try:
            note = self.staged_base if self.staged_note is not None else (
                mw.col.get_note(snapshot.id) if self.flush and snapshot.id else snapshot.live)
            model = note.note_type()
            if (model.get('id') != snapshot.model.get('id') or
                    [item['name'] for item in model['flds']] != [item['name'] for item in snapshot.model['flds']]):
                raise ValueError('Note type changed')
            watched = set(targets) | set(dependencies)
            live_notes = [snapshot.live, note]
            if snapshot.id:
                # Browser/editor drafts may not yet have reached the collection.
                for editor in matching_editors(snapshot):
                    editing = getattr(editor, 'note', None)
                    if editing is not None and getattr(editing, 'id', None) == snapshot.id:
                        live_notes.append(editing)
            if any(current.fields[index] != snapshot.original[index] for current in live_notes for index in watched):
                raise ValueError('Field changed')
            if any(fields[index] != snapshot.original[index] for fields in self.editor_fields for index in watched):
                raise ValueError('Editor field changed')
            if self.staged_note is not None:
                return self.staged_note
            return note
        except Exception:
            self.conflicts += len(targets)
            return None

    def _dictionary_result(self, snapshot, results, success, missed_css):
        self.completed_dictionary += 1
        self.dictionary_remaining[id(snapshot)] -= 1
        if self.dictionary.cancelled or self.window.dictionary.abort():
            return
        self.cache_result(snapshot, 'dictionary', {'results': dict(results),
            'errors': getattr(results, 'errors', []), 'success': success, 'missed_css': missed_css})
        self.result_queue.append(('dictionary', snapshot,
            lambda: self._apply_dictionary(snapshot, results, success, missed_css)))

    def cache_result(self, snapshot, kind, payload):
        if not self.flush:
            return
        values = payload['results'].values() if kind == 'dictionary' else (
            payload['result'].values() if payload['merged'] else [payload['result']])
        if not self.ai.query_settings.force_update and not any(value.get('result') for value in values):
            return
        future = self.cache_executor.submit(self.result_cache.put, snapshot, kind, payload, self.ai.query_settings)
        self.cache_pending[future] = snapshot

    def poll_cache(self):
        for future in list(self.cache_pending):
            if not future.done():
                continue
            snapshot = self.cache_pending.pop(future)
            try:
                key = future.result()
                if key:
                    self.cache_keys.setdefault(id(snapshot), []).append(key)
            except Exception as error:
                message = tr('待写入缓存保存失败，本次结果仅保留在内存中。')
                if message not in self.notices:
                    self.notices.append(message)
                logger.warning('Could not cache query result: %s', type(error).__name__)

    def poll_cleanup(self):
        if not self.cleanup_keys:
            return True
        if self.cleanup_future is None:
            self.phase = 'cleanup'
            self.cleanup_started_at = time.monotonic()
            self.cleanup_future = self.cache_executor.submit(self.result_cache.remove, list(self.cleanup_keys))
            return False
        if not self.cleanup_future.done():
            return False
        self.cleanup_seconds += time.monotonic() - self.cleanup_started_at
        try:
            self.cleanup_future.result()
            removed = set(self.cleanup_keys)
            self.cache_keys = {identity: [key for key in keys if key not in removed]
                               for identity, keys in self.cache_keys.items()}
        except Exception as error:
            self.notices.append(tr('字段已保存，但待写入缓存清理失败；恢复时会跳过已写入的内容。'))
            logger.warning('Could not clear saved result cache: %s', type(error).__name__)
        self.cleanup_keys.clear()
        self.cleanup_future = None
        return True

    def prepare_round(self, queries_done):
        now = time.monotonic()
        if self.writing or self.write_queue:
            return False
        if not self.collecting and not self.write_queue and not self.writing:
            self.save_seconds += now - self.round_started_at
            self.collecting = True
            self.next_write_at = now + self.write_interval
            started = time.monotonic()
            self.notify_saved()
            self.refresh_seconds += time.monotonic() - started
        cleanup_done = self.poll_cleanup()
        if not cleanup_done:
            return cleanup_done
        if queries_done and self.cache_pending:
            self.phase = 'cache'
            if self.cache_wait_started_at is None:
                self.cache_wait_started_at = now
            return True
        if not queries_done and now < self.next_write_at:
            self.phase = 'query'
            return True
        blocked = {id(snapshot) for snapshot in self.cache_pending.values()}
        grouped, deferred = {}, deque()
        for kind, snapshot, action in self.result_queue:
            identity = id(snapshot)
            settled = ((self.dictionary_remaining[identity] <= 0 or self.dictionary.cancelled) and
                       (self.ai_remaining[identity] <= 0 or self.ai.cancelled.is_set()))
            if identity in blocked or not settled:
                deferred.append((kind, snapshot, action))
            else:
                grouped.setdefault(identity, (snapshot, []))[1].append((kind, action))
        self.result_queue = deferred
        if grouped:
            if self.cache_wait_started_at is not None:
                self.cache_wait_seconds += now - self.cache_wait_started_at
                self.cache_wait_started_at = None
            self.round_keys = {identity: list(self.cache_keys.get(identity, [])) for identity in grouped}
            self.write_queue = deque(('batch', snapshot, actions) for snapshot, actions in grouped.values())
            self.collecting = False
            self.save_total, self.save_completed = len(grouped), 0
            self.round_started_at = now
            self.phase = 'save'
        elif self.cache_pending and self.result_queue:
            self.phase = 'cache'
            if queries_done and self.cache_wait_started_at is None:
                self.cache_wait_started_at = now
        else:
            self.phase = 'query'
            self.next_write_at = now + self.write_interval
        return True

    def _apply_dictionary(self, snapshot, results, success, missed_css):
        if self.dictionary.cancelled:
            return
        source = inspect_note(snapshot)[0]
        filtered = FieldResults()
        filtered.errors.extend(getattr(results, 'errors', []))
        note = None
        for target, result in results.items():
            current = self.current_note(snapshot, [target], [source])
            if current is not None:
                note = current
                filtered[target] = result
        if note is None and not results:
            note = self.current_note(snapshot, [], [])
        if note is not None:
            previous = self.dictionary.fields
            QueryWorkerManager.handle_result(self.dictionary, note, filtered, success, missed_css)
            if self.dictionary.fields > previous:
                self.mirror_live(snapshot, note, filtered)

    def mirror_live(self, snapshot, note, targets):
        if self.staged_note is not None:
            self.staged_targets.update(targets)
            return
        live = [snapshot.live]
        for editor in matching_editors(snapshot):
            editing = getattr(editor, 'note', None)
            if editing is not None and snapshot.id and getattr(editing, 'id', None) == snapshot.id:
                live.append(editing)
        for current in live:
            for target in targets:
                if current.fields[target] == snapshot.original[target]:
                    current.fields[target] = note.fields[target]

    def apply_ai(self, request, result):
        snapshot = request.tasks[0][0]
        names = [item['name'] for item in snapshot.model['flds']]
        referenced = set()
        for task in request.tasks:
            referenced.update(re.findall(r'\{\{\s*([^{}]+?)\s*\}\}', task[3].get('ai_prompt', '')))
            if task[3].get('cloze_word'):
                referenced.add(names[inspect_note(snapshot)[0]])
        dependencies = [names.index(name) for name in referenced if name in names]
        note = self.current_note(snapshot, [task[2] for task in request.tasks], dependencies)
        if note is None:
            return
        tasks = [(note, *task[1:]) for task in request.tasks]
        if request.merged:
            self.ai.apply_many(tasks, result)
        else:
            self.ai.apply(tasks[0], result)
        self.mirror_live(snapshot, note, [task[2] for task in tasks])

    def tick(self):
        if self.done:
            return
        if self.token != profile_token() or (self.guard and not self.guard()):
            self.cancel()
        if self.window.ai.abort():
            self.ai.was_cancelled = True
            self.ai.cancelled.set()
        if self.window.dictionary.abort():
            self.dictionary.cancelled = True
            for worker in self.dictionary.workers:
                worker.exit = True
        for future in list(self.pending):
            if not future.done():
                continue
            request = self.pending.pop(future)
            self.completed_ai += 1
            self.ai_remaining[id(request.tasks[0][0])] -= 1
            if not self.ai.cancelled.is_set():
                try:
                    result = future.result()
                    self.cache_result(request.tasks[0][0], 'ai', {'merged': request.merged,
                        'tasks': [list(task[1:]) for task in request.tasks],
                        'result': result})
                    self.result_queue.append(('ai', request.tasks[0][0],
                        lambda request=request, result=result: self.apply_ai(request, result)))
                except Exception as error:
                    self.ai.failed += 1
                    message = str(error) if isinstance(error, AIError) else tr('字段保存失败，原内容已恢复。')
                    self.ai.errors[message] = self.ai.errors.get(message, 0) + 1
                    logger.error('Background field update failed: %s', type(error).__name__)
                self.submit()
        dictionary_done = all(not worker.isRunning() for worker in self.dictionary.workers)
        self.poll_cache()
        queries_done = (not self.pending and dictionary_done and
                        (self.completed_dictionary >= len(self.regular) or self.dictionary.cancelled))
        if queries_done and self.query_finished_at is None:
            self.query_finished_at = time.monotonic()
        cleanup_done = self.prepare_round(queries_done)
        if not self.collecting:
            self._drain_writes()
        self.window.write_status.setVisible(self.writing or (not self.collecting and bool(self.write_queue)))
        if self.phase == 'cache':
            self.window.write_status.setText(tr('正在等待缓存落盘：剩余 %s 条') % len(self.cache_pending))
        elif self.phase == 'save':
            self.window.write_status.setText(tr('正在保存笔记：%s / %s') % (self.save_completed, self.save_total))
        elif self.phase == 'cleanup':
            self.window.write_status.setText(tr('正在清理已写入的缓存…'))
        self.window.write_status.setVisible(self.phase != 'query')
        self.window.ai.update(self.completed_ai + len(self.ai.validation_errors), self.ai.failed)
        self.window.dictionary.update(self.completed_dictionary, self.dictionary.fails)
        self.changed.emit()
        ai_writes = self.writing or bool(self.write_queue) or any(kind == 'ai' for kind, _, _ in self.result_queue)
        dictionary_writes = self.writing or bool(self.write_queue) or any(kind == 'dictionary' for kind, _, _ in self.result_queue)
        if not self.pending and not ai_writes:
            self.window.ai.finish()
        if dictionary_done and not dictionary_writes and (self.completed_dictionary >= len(self.regular) or self.dictionary.cancelled):
            self.window.dictionary.finish()
        if (not self.pending and dictionary_done and not self.writing and not self.write_queue and
                not self.result_queue and not self.cache_pending and self.collecting and cleanup_done):
            # Worker result signals may still be queued ahead of the next timer tick.
            if self.completed_dictionary < len(self.regular) and not self.dictionary.cancelled:
                return
            self.finish()

    def _write_error(self, kind, error):
        message = str(error) if isinstance(error, AIError) else tr('字段保存失败，原内容已恢复。')
        if kind == 'ai':
            self.ai.failed += 1
            self.ai.errors[message] = self.ai.errors.get(message, 0) + 1
        else:
            self.dictionary.fails += 1
            self.dictionary.errors.append(message)
        logger.error('Background write stopped: %s', getattr(error, 'code', type(error).__name__))

    def _drain_writes(self):
        if self.writing or self.done or self.cancelled:
            return
        # Limit immediate writes per tick so large result batches remain interactive.
        deadline = time.monotonic() + 0.01
        for _ in range(8):
            if not self.write_queue or self.writing or time.monotonic() >= deadline:
                break
            kind, snapshot, actions = self.write_queue.popleft()
            self.writing = True
            self.writing_kind = kind
            def ready(success, barrier, actions=actions, snapshot=snapshot):
                if self.done or self.cancelled:
                    return
                self.editor_fields = barrier.fields
                try:
                    if not success:
                        raise AIError(tr('无法确认编辑器中的最新内容，已跳过更新并保留原内容。'), code='editor_sync')
                    self._save_group(snapshot, actions, barrier)
                except Exception as error:
                    for action_kind in set(item[0] for item in actions):
                        self._write_error(action_kind, error)
                finally:
                    self.save_completed += 1
                    self.editor_fields = []
                    self.writing = False
                    self.writing_kind = None
                    self.barrier = None
            self.barrier = EditorBarrier(snapshot, ready)
            self.barrier.start()

    def _save_group(self, snapshot, actions, barrier):
        note = self.current_note(snapshot, [], [])
        if note is None:
            return
        staged = copy(note)
        staged.fields = list(note.fields)
        self.dictionary.query_settings = self.ai.query_settings = snapshot._query_settings
        self.staged_note, self.staged_targets = staged, set()
        self.staged_base = note
        before_ai = self.ai.updated_fields
        before_notes = set(self.ai.updated_notes)
        before_dictionary = (self.dictionary.counter, self.dictionary.fields, self.dictionary.skips)
        cancelled_results = False
        try:
            for kind, action in actions:
                if (kind == 'ai' and self.ai.cancelled.is_set()) or (kind == 'dictionary' and self.dictionary.cancelled):
                    cancelled_results = True
                    continue
                try:
                    action()
                except Exception as error:
                    self._write_error(kind, error)
            targets = set(self.staged_targets)
            self.staged_note = None
            if staged.fields != note.fields:
                original = list(note.fields)
                note.fields[:] = staged.fields
                try:
                    if self.flush:
                        self.save_note(note)
                except Exception:
                    note.fields[:] = original
                    self.ai.updated_fields = before_ai
                    self.ai.updated_notes = before_notes
                    self.dictionary.counter, self.dictionary.fields, self.dictionary.skips = before_dictionary
                    raise
                if self.flush:
                    mid = snapshot.model['id']
                    if mid not in self.styled_types:
                        self.styled_types.add(mid)
                        try:
                            self.merge_changes(apply_written_style(mw.col.models, mid, self.style_settings))
                        except Exception as error:
                            self.notices.append(tr('字段已保存，但 AI 样式更新失败，请检查全局 CSS。'))
                            logger.warning('AI CSS update failed: %s', type(error).__name__)
                if self.ai.updated_fields > before_ai:
                    self.ai.updated_notes.discard(id(staged))
                    self.ai.updated_notes.add(id(snapshot.live))
                self.mirror_live(snapshot, note, targets)
                if not barrier.refresh():
                    self.notices.append(tr('字段已保存，但编辑器刷新失败，请重新打开笔记。'))
            if not cancelled_results:
                self.cleanup_keys.extend(self.round_keys.get(id(snapshot), []))
        finally:
            self.staged_note = None
            self.staged_base = None
            self.staged_targets.clear()

    def background(self):
        self.is_background = True
        progress_hub().minimized.emit(self)
        self.changed.emit()

    def show_progress(self):
        if not self.done:
            self.window.setWindowModality(Qt.WindowModality.NonModal)
            self.window.show()
            self.window.raise_()

    def cancel(self, *_, wait=False):
        self.cancelled = True
        self.dictionary.cancelled = True
        for worker in self.dictionary.workers:
            worker.exit = True
        self.ai.was_cancelled = True
        self.ai.cancelled.set()
        self.write_queue.clear()
        self.result_queue.clear()
        if self.barrier:
            self.barrier.cancel()
            self.barrier = None
        self.writing = False
        self.writing_kind = None
        self.window.cancel_all()
        for future in self.pending:
            future.cancel()
        if wait:
            while not self.done:
                QApplication.processEvents()
                QThread.msleep(10)

    def finish(self):
        self.done = True
        ended = time.monotonic()
        query_ended = self.query_finished_at or ended
        if self.cache_wait_started_at is not None:
            self.cache_wait_seconds += ended - self.cache_wait_started_at
            self.cache_wait_started_at = None
        self.timings = {'query': query_ended - self.started_at,
                        'cache_wait': self.cache_wait_seconds,
                        'save': self.save_seconds,
                        'cleanup': self.cleanup_seconds}
        self.timer.stop()
        if self.executor:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.cache_executor.shutdown(wait=False)
        self.connections.clear()
        refresh_started = time.monotonic()
        self.notify_saved()
        if any(self.cache_keys.values()):
            self.notices.append(tr('已有返回结果留在待写入缓存中，可稍后恢复。'))
        self.window.finish()
        service_pool.clean()
        self.timings['refresh'] = self.refresh_seconds + time.monotonic() - refresh_started
        logger.info('Batch timing: query=%.3fs cache_wait=%.3fs save=%.3fs cleanup=%.3fs refresh=%.3fs notes=%s fields=%s',
                    self.timings['query'], self.timings['cache_wait'], self.timings['save'], self.timings['cleanup'],
                    self.timings['refresh'], len(self.snapshots), self.dictionary.fields + self.ai.updated_fields)
        if self in _jobs:
            _jobs.remove(self)
        if progress_hub().current is self:
            progress_hub().current = None
        report = ProgressReport(self)
        progress_hub().last = report
        progress_hub().completed.emit(report)
        self.changed.emit()
        self.finished.emit()
        if self.token == profile_token() and not self.silent:
            message = (tr('字段更新完成：词典 %s 个字段 · AI %s 个字段 · 失败 %s · 冲突跳过 %s') %
                       (self.dictionary.fields, self.ai.updated_fields, self.failed, self.conflicts))
            if self.cancelled or self.dictionary.cancelled or self.ai.was_cancelled:
                message += tr(' · 已取消')
            reasons = self.dictionary.errors + list(self.ai.errors) + self.ai.validation_errors
            if reasons:
                message += '\n' + tr('失败详情：%s') % '\n'.join(str(reason)[:250] for reason in reasons[:3])
            if self.notices:
                message += '\n' + '\n'.join(dict.fromkeys(self.notices))
            if getattr(self, 'notify_completion', True):
                tooltip(message, period=10000)
                if not self.is_background:
                    self.ai.show_failures(self.window.parentWidget())
            if self.on_complete:
                try:
                    self.on_complete(self.dictionary, self.ai)
                except Exception:
                    logger.exception('Could not refresh the interface after field updates')
        self.deleteLater()


def start_query_session(notes, **kwargs):
    job = active_job()
    if job:
        job.show_progress()
        tooltip(tr('已有更新任务正在运行，请完成或取消后再开始。'))
        return job
    job = QueryJob(notes, **kwargs)
    try:
        return job.start()
    except Exception:
        job.cancel()
        job.timer.start()
        raise


def cancel_jobs(wait=False):
    for job in list(_jobs):
        if wait:
            job.silent = True
        job.cancel(wait=wait)


def recover_results(parent=None):
    """Replay cached returns, with the same editor and conflict guards, without requests."""
    from ..service import QueryResult
    from ..utils.media import media_directory
    if active_job():
        active_job().show_progress()
        tooltip(tr('已有更新任务正在运行，请完成或取消后再开始。'))
        return None
    cache = ResultCache()
    records = cache.read()
    if not records:
        tooltip(tr('没有待恢复的结果。'))
        return None
    job = QueryJob([], parent=parent, start_in_background=True)
    job.background()
    groups = {}
    for key, record in records:
        identity = (record['nid'], tuple(record['original']), record['model']['id'])
        snapshot = groups.get(identity)
        if snapshot is None:
            try:
                live = mw.col.get_note(record['nid'])
            except Exception:
                job.notices.append(tr('笔记已不存在，已跳过其缓存结果。'))
                cache.remove([key])
                continue
            snapshot = NoteSnapshot(live, record['mappings'])
            snapshot.original = tuple(record['original'])
            snapshot.fields = list(record['original'])
            snapshot.model = record['model']
            snapshot._query_settings = SimpleNamespace(**record['settings'])
            snapshot.editor_ref = None
            groups[identity] = snapshot
        payload = record['payload']
        job.cache_keys.setdefault(id(snapshot), []).append(key)
        if record['kind'] == 'dictionary':
            results = FieldResults()
            results.errors.extend(payload['errors'])
            for target, value in payload['results'].items():
                missing = missing_media(value, media_directory())
                if missing:
                    results.errors.append(tr('恢复结果引用的媒体文件不存在：%s') % '、'.join(missing))
                else:
                    results[int(target)] = QueryResult(value)
            job.completed_dictionary += 1
            job.result_queue.append(('dictionary', snapshot,
                lambda snapshot=snapshot, results=results, payload=payload:
                    job._apply_dictionary(snapshot, results, payload['success'], payload['missed_css'])))
        else:
            tasks = [(snapshot, *task) for task in payload['tasks']]
            request = SimpleNamespace(tasks=tasks, merged=payload['merged'])
            result = ({name: QueryResult(value) for name, value in payload['result'].items()}
                      if request.merged else QueryResult(payload['result']))
            values = list(result.values()) if request.merged else [result]
            missing = [name for value in values for name in missing_media(value, media_directory())]
            job.completed_ai += 1
            if missing:
                job.ai.failed += 1
                message = tr('恢复结果引用的媒体文件不存在：%s') % '、'.join(missing)
                job.ai.errors[message] = job.ai.errors.get(message, 0) + 1
            else:
                job.result_queue.append(('ai', snapshot,
                    lambda request=request, result=result: job.apply_ai(request, result)))
    job.snapshots = list(groups.values())
    job.total = job.completed_ai + job.completed_dictionary
    job.window.ai.total = job.completed_ai
    job.window.dictionary.total = job.completed_dictionary
    return job.start()
