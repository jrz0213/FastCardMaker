"""Profile-local periodic queries: skip busy ticks and use starred mappings."""
from copy import deepcopy
import time
from types import SimpleNamespace

from aqt import mw
from aqt.qt import QObject, QTimer, QWidget
from ..context import config
from ..utils.media import profile_token
from ..utils.logger import logger
from ..service.ai_config import is_ai

MAX_BATCH = 100
MAX_ATTEMPTS = 3


def starred_mappings(model):
    conf = config.get_maps(model['id'])
    if isinstance(conf, list):
        conf = {'list': [conf], 'auto': 0}
    if not isinstance(conf, dict):
        return None
    index, choices = conf.get('auto', 0), conf.get('list', [])
    if choices and (type(index) is not int or not 0 <= index < len(choices)):
        index = 0
    if type(index) is not int or not 0 <= index < len(choices):
        return None
    choice = choices[index]
    fields = deepcopy(choice if isinstance(choice, list) else choice.get('fields', []))
    positions = {field['name']: i for i, field in enumerate(model['flds'])}
    normalized = []
    for index, name in enumerate(positions):
        mapping = next((item for item in fields if item.get('fld_name') == name), None)
        if mapping is None and index < len(fields) and not fields[index].get('fld_name'):
            mapping = fields[index]
        mapping = deepcopy(mapping or {'ignore': True})
        mapping.update(fld_name=name, fld_ord=index, skip_valued=True)
        unique = mapping.get('dict_unique')
        if unique and not is_ai(unique) and not config.dicts.get(unique, {}).get('enabled', False):
            mapping['ignore'] = True
        normalized.append(mapping)
    if not any(item.get('word_checked') for item in normalized):
        return None
    return normalized


def empty_targets(note, mappings):
    return [i for i, item in enumerate(mappings)
            if not item.get('word_checked') and not item.get('ignore', True)
            and item.get('dict_unique') and not note.fields[i].strip()]


class AutomaticQueries(QObject):
    def __init__(self):
        super().__init__()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.token = None
        self.signature = None
        self.job = None
        self.countdown = None

    def configure(self):
        settings = config.auto_run
        enabled = bool(settings.get('enabled', False))
        try:
            interval = max(1, min(1440, int(settings.get('interval_minutes', 5))))
            models = tuple(sorted({int(value) for value in settings.get('model_ids', [])}))
        except (TypeError, ValueError):
            interval, models = 5, ()
        token = profile_token()
        signature = (token, enabled, interval, models)
        if signature == self.signature:
            return
        previous = self.signature
        self.signature, self.token = signature, token
        self.timer.stop()
        if self.countdown:
            self.countdown.reject()
            self.countdown = None
        if self.job and not self.job.done:
            self.job.cancel()
        if not enabled or not getattr(mw, 'col', None):
            return
        # Store the activation boundary once, so reopening Anki doesn't lose
        # notes created while it was closed. Re-enabling starts a new boundary.
        state = config.data.get('_auto_run_state', {})
        if not isinstance(state, dict) or not state.get('since') or (previous and previous[0] == token and not previous[1]):
            state = {'since': int(time.time() * 1000), 'cursors': {}, 'pending': {}}
            config.update({'_auto_run_state': state})
        self.timer.start(interval * 60_000)

    def stop(self):
        self.timer.stop()
        if self.countdown:
            self.countdown.reject()
            self.countdown = None
        if self.job and not self.job.done:
            self.job.cancel()
        self.token = self.signature = None
        self.job = None

    def _allowed(self):
        from .background import active_job
        from ..service.refresh import get_updater
        from .result_cache import ResultCache
        return (self.token == profile_token() and config.auto_run.get('enabled', False)
                and getattr(mw, 'col', None) and not active_job()
                and not get_updater().busy and not ResultCache().pending())

    def tick(self):
        from .background import start_query_session
        try:
            if self.countdown is None and self._allowed():
                self._launch(start_query_session, announce=True)
        except Exception as error:
            logger.warning('Automatic query tick failed: %s', type(error).__name__)

    def _countdown_ready(self, start):
        self.countdown = None
        try:
            if self._allowed():
                self._launch(start)
        except Exception as error:
            logger.warning('Automatic query launch failed: %s', type(error).__name__)

    def _launch(self, start, announce=False):
        state = deepcopy(config.data.get('_auto_run_state', {}))
        since = state.get('since')
        if type(since) is not int:
            return
        cursors, pending = state.setdefault('cursors', {}), state.setdefault('pending', {})
        selected = {str(value) for value in config.auto_run.get('model_ids', [])}
        models = []
        for model in mw.col.models.all():
            if str(model['id']) in selected:
                mappings = starred_mappings(model)
                if mappings:
                    models.append((model, mappings))
        notes, planned = [], {}
        for model, mappings in sorted(models, key=lambda item: cursors.get(str(item[0]['id']), since)):
            mid = str(model['id'])
            waiting = pending.setdefault(mid, {})
            for nid in list(waiting):
                if waiting[nid] >= MAX_ATTEMPTS:
                    del waiting[nid]
            room = min(25, MAX_BATCH - len(notes))
            if room <= 0:
                break
            if len(waiting) < room:
                ids = mw.col.db.list('select id from notes where mid = ? and id > ? order by id limit ?',
                                     model['id'], cursors.get(mid, since), room - len(waiting))
                for nid in ids:
                    waiting.setdefault(str(nid), 0)
                    cursors[mid] = nid
            for nid in list(waiting)[:room]:
                try:
                    note = mw.col.get_note(int(nid))
                    if note.note_type()['id'] != model['id'] or not empty_targets(note, mappings):
                        del waiting[nid]
                        continue
                    source = next(i for i, item in enumerate(mappings) if item.get('word_checked'))
                    if not note.fields[source].strip():
                        # The note can be retried on a later tick while its
                        # source is still being edited; bound all attempts.
                        waiting[nid] += 1
                        continue
                    note._query_mappings = deepcopy(mappings)
                    notes.append(note)
                    planned[(mid, nid)] = mappings
                    waiting[nid] += 1
                except Exception:
                    waiting.pop(nid, None)
        if notes and announce:
            from ..gui.automatic_prompt import AutomaticPrompt
            prompt = self.countdown = AutomaticPrompt(mw if isinstance(mw, QWidget) else None,
                                                      lambda: self._countdown_ready(start))
            def closed(*_):
                if self.countdown is prompt:
                    self.countdown = None
                prompt.deleteLater()
            prompt.finished.connect(closed)
            prompt.show()
            return
        config.update({'_auto_run_state': state})
        if not notes:
            return
        token = self.token
        def completed(dictionary, ai):
            self.job = None
            if token != self.token or token != profile_token():
                return
            latest = deepcopy(config.data.get('_auto_run_state', {}))
            for (mid, nid), mappings in planned.items():
                waiting = latest.get('pending', {}).get(mid, {})
                try:
                    note = mw.col.get_note(int(nid))
                    complete = not empty_targets(note, mappings)
                except Exception:
                    complete = True
                if complete or waiting.get(nid, MAX_ATTEMPTS) >= MAX_ATTEMPTS:
                    waiting.pop(nid, None)
            config.update({'_auto_run_state': latest})
        settings = SimpleNamespace(force_update=False, ignore_accents=config.ignore_accents, cloze_str=config.cloze_str)
        self.job = start(notes, query_settings=settings, on_complete=completed, start_in_background=True)
        self.job.notify_completion = False
        self.job.background()


_scheduler = None


def get_scheduler():
    global _scheduler
    if _scheduler is None:
        _scheduler = AutomaticQueries()
    return _scheduler


def configure_automatic():
    get_scheduler().configure()
