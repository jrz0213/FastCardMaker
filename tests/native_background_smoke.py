"""Optional smoke check against a native Anki SDK and a temporary collection.

Run this file directly with Anki and PyQt6 on PYTHONPATH. Never opens an existing
collection, and all AI responses are simulated.
"""
import sys
import tempfile
import threading
import time
import json
from types import SimpleNamespace
from pathlib import Path
from unittest.mock import patch

from anki.collection import Collection

native_modules = {key: value for key, value in sys.modules.items()
                  if key == 'anki' or key.startswith('anki.')}
from test_gui_runtime import GuiRuntimeTests


def main():
    GuiRuntimeTests.setUpClass()
    host = GuiRuntimeTests()
    host.setUp()
    collection = None
    release = threading.Event()
    try:
        module, runner, base, _, root = host.background_host()
        for key in list(sys.modules):
            if key == 'anki' or key.startswith('anki.'):
                del sys.modules[key]
        sys.modules.update(native_modules)
        with tempfile.TemporaryDirectory(prefix='fwq-native-smoke-', ignore_cleanup_errors=True) as folder:
            collection = Collection(str(Path(folder) / 'test.anki2'))
            model = collection.models.new('Background smoke')
            for name in ('Word', 'Meaning', 'Example'):
                collection.models.add_field(model, collection.models.new_field(name))
            template = collection.models.new_template('Card')
            template.update(qfmt='{{Word}}', afmt='{{FrontSide}}<hr>{{Meaning}}')
            collection.models.add_template(model, template)
            collection.models.add(model)
            root.col = collection
            formatting = host.load('utils.ai_format')
            old_css = collection.models.get(model['id'])['css']
            formatting.save_style(collection.models, model['id'], formatting.DEFAULT_CSS, True)
            styled_css = collection.models.get(model['id'])['css']
            assert formatting.START in styled_css
            assert formatting.save_style(collection.models, model['id'], formatting.DEFAULT_CSS, True) is None
            assert collection.models.get(model['id'])['css'] == styled_css
            formatting.save_style(collection.models, model['id'], formatting.DEFAULT_CSS, False)
            assert collection.models.get(model['id'])['css'] == old_css
            note = collection.new_note(model)
            note.fields = ['apple', '', '']
            collection.add_note(note, 1)
            mappings = [{'fld_name': 'Word', 'word_checked': True},
                        {'fld_ord': 1, 'dict_unique': 'ai:test',
                         'ai_prompt': 'Explain {{Word}}', 'ignore': False}]
            host.host.config.ai_css_enabled = True
            host.host.config.ai_css = formatting.DEFAULT_CSS
            host.host.config.ai_styles = {str(model['id']): {'enabled': True}}
            host.host.config.get_maps = lambda mid: {'list': [{'name': 'Saved', 'fields': mappings}], 'def': 0}
            type_entry = host.load('gui.type_query')
            assert type_entry.selected_model_ids(SimpleNamespace(mw=root, selectedNotes=lambda: [note.id])) == {model['id']}
            dialog = type_entry.TypeQueryDialog(root, {model['id']})
            host.widgets.append(dialog)
            launched = []
            start = module.start_query_session
            def track(notes, **kwargs):
                job = start(notes, **kwargs)
                launched.append(job)
                return job
            with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='An apple')):
                with patch.object(module, 'start_query_session', side_effect=track):
                    dialog.run()
                    host.pump_until(lambda: bool(launched))
                job = launched[0]
                job.background()
                host.pump_until(lambda: job.done)
            assert collection.get_note(note.id).fields[1] == 'An apple'
            assert job.ai.updated_fields == 1 and job.failed == 0
            injected = collection.models.get(model['id'])['css']
            assert formatting.START in injected
            host.host.config.ai_css = formatting.DEFAULT_CSS.replace('line-height: 1.6', 'line-height: 1.9')
            with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='An apple')):
                unchanged = module.start_query_session([collection.get_note(note.id)], mappings=mappings, model=model)
                unchanged.background()
                host.pump_until(lambda: unchanged.done)
            assert collection.models.get(model['id'])['css'] == injected
            host.host.config.ai_css_enabled = False
            started = threading.Event()
            def delayed(*args, **kwargs):
                started.set()
                release.wait(3)
                return base.QueryResult(result='Outdated answer')
            with patch.object(runner, 'query_ai', side_effect=delayed):
                job = module.start_query_session([collection.get_note(note.id)], mappings=mappings, model=model)
                job.background()
                host.pump_until(started.is_set)
                changed = collection.get_note(note.id)
                changed.fields[0] = 'banana'
                collection.update_note(changed)
                release.set()
                host.pump_until(lambda: job.done)
            assert collection.get_note(note.id).fields == ['banana', 'An apple', '']
            assert job.conflicts == 1
            with patch.object(runner, 'query_ai', return_value=base.QueryResult(result='Discarded')):
                job = module.start_query_session([collection.get_note(note.id)], mappings=mappings, model=model)
                job.background()
                job.cancel()
                host.pump_until(lambda: job.done)
            assert collection.get_note(note.id).fields[1] == 'An apple'
            # Exercise the scheduler's real SQL scan and per-note starred map.
            automatic = host.load('query.automatic')
            cfg = host.host.config
            cfg.auto_run = {'enabled': True, 'interval_minutes': 5, 'model_ids': [model['id']]}
            cfg.data = {'_auto_run_state': {'since': note.id, 'cursors': {}, 'pending': {}}}
            cfg.update.side_effect = lambda values: cfg.data.update(values)
            cfg.get_maps = lambda mid: {'list': [{'fields': mappings}], 'auto': 0, 'def': 0}
            cfg.cloze_str = '{{c1::%s}}'
            fresh = collection.new_note(model)
            fresh.fields = ['cherry', '', 'manual example']
            collection.add_note(fresh, 1)
            scheduler = automatic.AutomaticQueries()
            scheduler.configure()
            cfg.ai_send_mode = 'note'
            with patch.object(runner, 'query_ai_many', return_value={'Meaning': base.QueryResult(result='Scheduled answer')}):
                scheduler._launch(module.start_query_session)
                scheduled_job = scheduler.job
                assert scheduled_job is not None and scheduled_job.is_background
                assert scheduled_job.ai.requests[0].merged
                host.pump_until(lambda: scheduled_job.done)
            assert collection.get_note(fresh.id).fields == ['cherry', 'Scheduled answer', 'manual example']
            assert collection.get_note(note.id).fields == ['banana', 'An apple', '']
            scheduler.stop()
            # Persist a returned audio reference, close/reopen the native collection,
            # and recover without another model request or another media copy.
            audio = Path(root.pm.profileFolder()) / 'collection.media' / 'fwq-smoke.mp3'
            audio.parent.mkdir(parents=True, exist_ok=True)
            original_bytes = b'native-smoke-media-bytes'
            audio.write_bytes(original_bytes)
            interrupted = collection.new_note(model)
            interrupted.fields = ['grape', '', '']
            collection.add_note(interrupted, 1)
            interrupted_id = interrupted.id
            cfg.ai_send_mode = 'field'
            two_fields = [mappings[0], dict(mappings[1], ai_prompt='fast'),
                          dict(mappings[1], fld_ord=2, ai_prompt='slow')]
            release.clear()
            def interrupted_query(unique, prompt, *args, **kwargs):
                if prompt == 'slow':
                    release.wait(3)
                return base.QueryResult(result='[sound:fwq-smoke.mp3]')
            with patch.object(runner, 'query_ai', side_effect=interrupted_query):
                job = module.start_query_session([interrupted], mappings=two_fields, model=model)
                job.background()
                host.pump_until(lambda: job.completed_ai == 1)
                host.pump_until(lambda: not job.cache_pending)
                assert collection.get_note(interrupted_id).fields == ['grape', '', '']
                assert job.result_cache.pending()
                job.cancel()
                release.set()
                host.pump_until(lambda: job.done)
            collection.close()
            collection = Collection(str(Path(folder) / 'test.anki2'))
            root.col = collection
            with patch.object(runner, 'query_ai', side_effect=AssertionError('Recovery must not call AI')) as query:
                recovery = module.recover_results()
                host.pump_until(lambda: recovery.done)
                query.assert_not_called()
            assert collection.get_note(interrupted_id).fields == ['grape', '[sound:fwq-smoke.mp3]', '']
            assert audio.read_bytes() == original_bytes
            assert not recovery.result_cache.pending()
            # Reproduce the screenshot's 290 queried notes / 105 changed fields.
            # Dictionary returns are simulated; collection writes and cache I/O are real.
            workload = []
            for index in range(290):
                sample = collection.new_note(model)
                sample.fields = ['sample-%s' % index, '', '']
                collection.add_note(sample, 1)
                workload.append(sample)
            cfg.thread_number = 16
            dictionary_maps = [mappings[0], {'fld_ord': 1, 'dict_unique': 'local',
                                             'dict_fld_ord': 0, 'ignore': False}]
            worker = host.load('query.worker')
            def simulated_dictionary(snapshot, *args, **kwargs):
                index = int(snapshot.fields[0].split('-')[1])
                results = module.FieldResults()
                results[1] = base.QueryResult(result='definition' if index < 105 else '')
                return results, 1, []
            job = module.QueryJob(workload, mappings=dictionary_maps, model=model, start_in_background=True)
            puts, removals = [], []
            original_put, original_remove = job.result_cache.put, job.result_cache.remove
            def counted_put(*args):
                puts.append(threading.get_ident())
                return original_put(*args)
            def counted_remove(keys):
                removals.append(len(keys))
                return original_remove(keys)
            job.result_cache.put, job.result_cache.remove = counted_put, counted_remove
            gaps, previous = [], [time.monotonic()]
            heartbeat = host.qt.QTimer()
            heartbeat.setInterval(10)
            def beat():
                now = time.monotonic()
                gaps.append(now - previous[0])
                previous[0] = now
            heartbeat.timeout.connect(beat)
            heartbeat.start()
            with patch.object(worker, 'query_flds', side_effect=simulated_dictionary):
                job.start()
                job.background()
                host.pump_until(lambda: job.done, timeout=30)
            heartbeat.stop()
            assert job.completed == 290 and job.dictionary.fields == 105
            assert len(puts) == 105 and removals == [105]
            assert all(thread != threading.get_ident() for thread in puts)
            assert not job.result_cache.pending()
            print(json.dumps({'benchmark': '290 notes / 105 changed fields; simulated dictionary',
                              'timings_seconds': job.timings, 'cache_puts': len(puts),
                              'cache_cleanup_transactions': len(removals),
                              'qt_heartbeat_max_gap_seconds': max(gaps, default=0)}, ensure_ascii=False))
            collection.close()
            collection = None
        print('Native Anki SDK: saved fields, source conflict, cancellation, scheduled scan, durable recovery after reopening, and unchanged media all passed.')
    finally:
        release.set()
        host.doCleanups()
        if collection:
            collection.close()


if __name__ == '__main__':
    main()
