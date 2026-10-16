"""Run dictionary and AI queues together; all note writes stay on the UI thread."""

from .worker import QueryWorkerManager
from .ai_runner import AIQueryRunner, dictionary_notes
from ..gui.query_progress import QueryProgressWindow
from ..service.ai_config import ai_send_rate

_active_sessions = []


def cancel_active_sessions(wait=False):
    from .background import cancel_jobs
    cancel_jobs(wait=wait)
    for dictionary, ai in list(_active_sessions):
        dictionary.cancelled = True
        for worker in dictionary.workers:
            worker.exit = True
        ai.cancel(wait=wait)
        if wait:
            dictionary.join()


def run_query_session(notes, flush=True, fields=None, mappings=None, model=None, writer=None, parent=None):
    from ..service.script_updates import expire_for_plugin
    expire_for_plugin()
    ai = AIQueryRunner(notes, fields=fields, flush=flush, mappings=mappings, model=model, writer=writer)
    regular = dictionary_notes(notes, fields, mappings)
    dictionary = QueryWorkerManager()
    dictionary.flush = flush
    dictionary.writer = writer
    dictionary.query_fields = fields
    dictionary.query_mappings = mappings
    dictionary.include_ai = False
    for note in regular:
        dictionary.queue.put(note)
    ai_total = ai.total_requests
    window = None
    if regular and ai_total:
        window = QueryProgressWindow(len(regular), ai_total, ai_send_rate(), parent)
        dictionary.progress = window.dictionary
    completed = False
    session = (dictionary, ai)
    _active_sessions.append(session)
    try:
        if regular:
            dictionary.start()
        ai.run(parent, progress=window.ai if window else None,
               on_tick=dictionary.poll if window else None, report=False)
        completed = True
    finally:
        if regular:
            if not completed:
                dictionary.cancelled = True
                for worker in dictionary.workers:
                    worker.exit = True
            dictionary.join()
        if window:
            window.finish()
        _active_sessions.remove(session)
    if dictionary.is_current_profile():
        ai.show_failures(parent)
    return dictionary, ai
