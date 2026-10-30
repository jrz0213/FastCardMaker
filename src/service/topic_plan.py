"""Validate topic edits and allocate identifiers locally, without reusing them."""
from copy import deepcopy
from datetime import datetime


def apply_changes(current, changes, next_id, allowed=None):
    if not isinstance(changes, list):
        raise ValueError('changes must be a list')
    known = {c['id'] for c in current}
    touched = set()
    prepared = []
    for change in changes:
        if not isinstance(change, dict):
            raise ValueError('Invalid change')
        action = change.get('action')
        cards = change.get('cards', [])
        if action == 'add':
            if change.get('id') is not None:
                raise ValueError('New identifiers are allocated locally')
            ids = []
        elif action in ('replace', 'delete'):
            ids = [change.get('id')]
        else:
            raise ValueError('Unknown action')
        if action == 'replace' and (not isinstance(cards, list) or len(cards) != 1):
            raise ValueError('Replacement requires exactly one card')
        if action == 'delete' and cards != []:
            raise ValueError('Deletion cannot include cards')
        if not isinstance(ids, list) or any(type(i) is not int for i in ids):
            raise ValueError('Invalid identifiers')
        if len(set(ids)) != len(ids) or not set(ids) <= known or touched.intersection(ids):
            raise ValueError('Unknown or repeated identifiers')
        if allowed is not None and not set(ids) <= set(allowed):
            raise ValueError('Edit outside selection')
        if not isinstance(cards, list) or (not ids and not cards):
            raise ValueError('Invalid cards')
        for card in cards:
            if not isinstance(card, dict) or any(not isinstance(card.get(k), str) or not card[k].strip() for k in ('topic', 'content')):
                raise ValueError('Incomplete card')
        touched.update(ids)
        after = change.get('after_id')
        if after is not None and (action != 'add' or type(after) is not int or after not in known):
            raise ValueError('Invalid insertion anchor')
        prepared.append((ids, cards, after))
    result = deepcopy(current)
    next_id = max(next_id, max(known, default=0) + 1)
    # Additions always follow all surviving original cards.
    prepared.sort(key=lambda item: not bool(item[0]))
    anchors = {}
    for ids, cards, after in prepared:
        position = min((i for i, c in enumerate(result) if c['id'] in ids), default=len(result))
        if after is not None:
            anchor = anchors.get(after, after)
            found = next((i for i, c in enumerate(result) if c['id'] == anchor), None)
            if found is None:
                raise ValueError('Insertion anchor was deleted')
            position = found + 1
        originals = {c['id']: c for c in result}
        result = [c for c in result if c['id'] not in ids]
        added = []
        for card in cards:
            # Replacement keeps its identifier; additions never reuse retired IDs.
            same = len(ids) == len(cards) == 1
            ident = ids[0] if same else next_id
            if not same:
                next_id += 1
            added.append({'id': ident, 'topic': card['topic'], 'content': card['content'],
                          'created_at': originals[ident]['created_at'] if same else datetime.now().astimezone().isoformat(timespec='seconds')})
        result[position:position] = added
        if after is not None and added:
            anchors[after] = added[-1]['id']
    if len(result) > 100:
        raise ValueError('Too many cards')
    return result, next_id
