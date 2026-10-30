"""Validate a complete draft before changing any live conversation state."""
from copy import deepcopy


def validate_draft(value):
    data = deepcopy(value)
    if not isinstance(data, dict):
        raise ValueError('Invalid draft')
    def cards(items, unique=True):
        if not isinstance(items, list):
            raise ValueError('Invalid cards')
        ids = []
        for item in items:
            if not isinstance(item, dict) or type(item.get('id')) is not int or item['id'] < 1:
                raise ValueError('Invalid identifier')
            if any(not isinstance(item.get(k), str) for k in ('topic', 'content', 'created_at')):
                raise ValueError('Invalid card content')
            if 'version' in item and (type(item['version']) is not int or item['version'] < 1):
                raise ValueError('Invalid version')
            ids.append(item['id'])
        if unique and len(set(ids)) != len(ids):
            raise ValueError('Duplicate identifiers')
    cards(data['cards'])
    if not isinstance(data['history'], list):
        raise ValueError('Invalid history')
    for turn in data['history']:
        if not isinstance(turn, dict) or turn.get('role') not in ('user', 'assistant', 'system') or not isinstance(turn.get('content'), str):
            raise ValueError('Invalid turn')
        if 'topic_cards' in turn:
            cards(turn['topic_cards'])
    versions = data.setdefault('versions', {})
    if not isinstance(versions, dict):
        raise ValueError('Invalid versions')
    for key, items in versions.items():
        if not isinstance(key, str) or not key.isdigit() or int(key) < 1:
            raise ValueError('Invalid version key')
        cards(items, unique=False)
        if any(item['id'] != int(key) for item in items):
            raise ValueError('Mismatched versions')
    added = data.setdefault('added_ids', [])
    if not isinstance(added, list) or any(type(i) is not int or i < 1 for i in added):
        raise ValueError('Invalid added IDs')
    positions = data.get('field_positions', {})
    if not isinstance(positions, dict) or any(not isinstance(item, dict) or
            any(not isinstance(v, str) for v in item.values()) for item in positions.values()):
        raise ValueError('Invalid field positions')
    for key in ('next_id', 'count'):
        number = data.get(key, 1 if key == 'next_id' else 0)
        if type(number) is not int or number < (1 if key == 'next_id' else 0):
            raise ValueError('Invalid number')
        data[key] = number
    for key in ('original', 'message', 'deck'):
        if key in data and not isinstance(data[key], str):
            raise ValueError('Invalid text')
    pending = data.get('pending')
    if pending is not None:
        if not isinstance(pending, (list, tuple)) or len(pending) != 2 or type(pending[1]) is not int:
            raise ValueError('Invalid pending plan')
        cards(pending[0])
    return data
