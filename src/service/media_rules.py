"""Optional media-path repairs, independent of exported dictionary fields."""
from bs4 import BeautifulSoup
from .audio_rules import audio_path, validate_audio_rule
from .dictionary_assets import read_asset


def validate_media(rules):
    if not isinstance(rules, list) or len(rules) > 12:
        raise ValueError('Invalid media rules')
    for rule in rules:
        if not isinstance(rule, dict) or set(rule) != {'selector', 'audio', 'limit'}:
            raise ValueError('Invalid media rule')
        if not isinstance(rule['selector'], str) or not 0 < len(rule['selector']) <= 400:
            raise ValueError('Invalid media selector')
        BeautifulSoup('', 'html.parser').select(rule['selector'])
        if type(rule['limit']) is not int or not 1 <= rule['limit'] <= 50:
            raise ValueError('Invalid media limit')
        validate_audio_rule(rule['audio'])


def repair_media(html, rules, builder=None, dict_path=None):
    if not rules:
        return html
    soup = BeautifulSoup(html, 'html.parser')
    changed = False
    for rule in rules:
        for node in soup.select(rule['selector'])[:rule['limit']]:
            # Repeated adaptation must never transform an already resolved sound link.
            if str(node.get('href', '')).startswith('sound:') or node.get('data-fastcm-media') == 'resolved':
                continue
            key = audio_path(node, rule['audio'])
            if builder is not None and not read_asset(builder, dict_path, key, 1):
                raise ValueError('Media repair could not find resource: ' + key)
            attribute = rule['audio']['attribute']
            if attribute.lower().startswith('on'):
                node.attrs.pop(attribute, None)
            if node.name in ('audio', 'source'):
                node['src'] = key
            else:
                node.name = 'a'
                node['href'] = 'sound:' + key
            changed = True
            node['data-fastcm-media'] = 'resolved'
    return str(soup) if changed else html
