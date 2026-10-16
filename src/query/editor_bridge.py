"""Drain editor saves before writing; never guess at outstanding webview edits."""

from aqt.qt import QApplication, QTimer
from ..utils.logger import logger


def editor_matches(editor, snapshot):
    try:
        note = getattr(editor, 'note', None)
        if note is not None:
            return note is snapshot.live or (snapshot.id and getattr(note, 'id', None) == snapshot.id)
        return bool(snapshot.id and getattr(editor, 'nid', None) == snapshot.id)
    except RuntimeError:
        return False


def matching_editors(snapshot):
    editors, seen = [], set()
    reference = getattr(snapshot, 'editor_ref', None)
    hinted = reference() if reference else None
    if hinted is not None and editor_matches(hinted, snapshot):
        editors.append(hinted)
        seen.add(id(hinted))
    for window in QApplication.topLevelWidgets():
        if not window.isVisible():
            continue
        editor = getattr(window, 'editor', None)
        if editor is not None and id(editor) not in seen and editor_matches(editor, snapshot):
            editors.append(editor)
            seen.add(id(editor))
    return editors


class EditorBarrier:
    """A bounded, asynchronous barrier for classic and modern Anki editors."""
    TIMEOUT_MS = 2500

    def __init__(self, snapshot, on_ready):
        self.snapshot, self.on_ready = snapshot, on_ready
        self.editors = matching_editors(snapshot)
        self.fields = []
        self.active = True
        self.index = 0

    def start(self):
        QTimer.singleShot(self.TIMEOUT_MS, self._timeout)
        self._next()

    def cancel(self):
        self.active = False
        self.on_ready = None

    def _finish(self, success):
        if not self.active:
            return
        callback = self.on_ready
        self.cancel()
        callback(success, self)

    def _timeout(self):
        self._finish(False)

    def _next(self):
        if not self.active:
            return
        if self.index >= len(self.editors):
            self._finish(True)
            return
        editor = self.editors[self.index]
        self.index += 1
        try:
            if not editor_matches(editor, self.snapshot):
                self._finish(False)
                return
            save = getattr(editor, 'call_after_note_saved', None) or getattr(editor, 'saveNow', None)
            if callable(save):
                save(lambda: self._read(editor), keepFocus=True)
            else:
                self._read(editor)
        except Exception as error:
            logger.warning('Editor synchronization failed: %s', type(error).__name__)
            self._finish(False)

    def _read(self, editor):
        if not self.active:
            return
        try:
            if not editor_matches(editor, self.snapshot):
                self._finish(False)
                return
            read = getattr(editor, 'get_note_info', None)
            if callable(read):
                read(lambda info: self._observed(editor, info))
            else:
                note = getattr(editor, 'note', None)
                if note is None:
                    self._finish(False)
                    return
                self.fields.append(tuple(note.fields))
                self._next()
        except Exception as error:
            logger.warning('Editor read failed: %s', type(error).__name__)
            self._finish(False)

    def _observed(self, editor, info):
        if not self.active:
            return
        try:
            if (not editor_matches(editor, self.snapshot) or getattr(info, 'id', None) != self.snapshot.id or
                    getattr(info, 'mid', None) != self.snapshot.model.get('id')):
                self._finish(False)
                return
            self.fields.append(tuple(info.fields))
            self._next()
        except Exception as error:
            logger.warning('Editor snapshot failed: %s', type(error).__name__)
            self._finish(False)

    def refresh(self):
        success = True
        for editor in self.editors:
            if not editor_matches(editor, self.snapshot):
                continue
            try:
                modern = getattr(editor, 'reload_note', None)
                if callable(modern):
                    modern()
                else:
                    note = getattr(editor, 'note', None)
                    setter = getattr(editor, 'set_note', None) or getattr(editor, 'setNote', None)
                    if note is not None and callable(setter):
                        setter(note, focusTo=getattr(editor, 'currentField', None))
            except Exception as error:
                # Saving has succeeded; a closed editor must not roll it back.
                success = False
                logger.warning('Saved note could not be displayed: %s', type(error).__name__)
        return success
