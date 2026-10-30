"""Preview only complete objects in cards arrays, never repair partial JSON."""
import json


def complete_cards(text):
    decoder = json.JSONDecoder()
    cards = []
    i = 0
    while i < len(text):
        if text[i] != '"':
            i += 1
            continue
        try:
            token, end = decoder.raw_decode(text, i)
        except ValueError:
            break
        i = end
        if token != 'cards':
            continue
        tail = text[i:].lstrip()
        if not tail.startswith(':'):
            continue
        i = len(text) - len(tail) + 1
        while i < len(text) and text[i].isspace():
            i += 1
        if i >= len(text) or text[i] != '[':
            continue
        i += 1
        while i < len(text):
            while i < len(text) and (text[i].isspace() or text[i] == ','):
                i += 1
            if i >= len(text) or text[i] == ']':
                break
            try:
                value, i = decoder.raw_decode(text, i)
            except ValueError:
                return cards
            if isinstance(value, dict) and all(isinstance(value.get(k), str) and value[k].strip() for k in ('topic', 'content')):
                cards.append(value)
    return cards
