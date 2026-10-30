"""Muted note-type choices indicate that no saved mapping exists."""


def has_saved_configuration(value):
    if isinstance(value, list):
        return bool(value)
    return isinstance(value, dict) and isinstance(value.get('list'), list) and bool(value['list'])


def style_note_types(combo):
    from aqt.qt import Qt, QPalette
    from ..context import config
    muted = combo.palette().brush(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text)
    for index in range(combo.count()):
        mid = combo.itemData(index)
        present = mid is not None and has_saved_configuration(config.get_maps(mid))
        combo.setItemData(index, None if present else muted, Qt.ItemDataRole.ForegroundRole)
