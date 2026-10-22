"""AI reply envelopes are separate from the provider's transport response."""
import json
import re


def decode_reply(text):
    raw = text.strip()
    fence = re.fullmatch(r'```(?:json)?\s*\n([\s\S]*?)\n\s*```', raw, re.I)
    if fence:
        raw = fence.group(1)
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError('Duplicate AI reply field')
            value[key] = item
        return value
    try:
        value = json.loads(raw, object_pairs_hook=unique)
    except json.JSONDecodeError:
        return None
    if not isinstance(value, dict) or not set(value) & {'ai-message', 'code', 'rules'}:
        return None  # Existing rules and Python replies remain readable.
    if set(value) - {'ai-message', 'code', 'rules'} or 'code' in value and 'rules' in value:
        raise ValueError('Invalid AI reply fields')
    if 'ai-message' in value and not isinstance(value['ai-message'], str):
        raise ValueError('AI message must be text')
    if 'code' in value and (not isinstance(value['code'], str) or not value['code'].strip()):
        raise ValueError('AI code must be a complete nonempty script')
    if 'rules' in value and not isinstance(value['rules'], dict):
        raise ValueError('AI rules must be an object')
    return value


def reply_content(text, rule_mode):
    value = decode_reply(text)
    if value is None:
        return text, False
    expected, other = ('rules', 'code') if rule_mode else ('code', 'rules')
    if other in value:
        raise ValueError('AI reply does not match the selected output mode')
    if expected not in value:
        return '', True
    return (json.dumps(value['rules'], ensure_ascii=False) if rule_mode else value['code']), False


def display_reply(text):
    """Hide the envelope's label on screen; keep the original response elsewhere."""
    try:
        value = decode_reply(text)
    except ValueError:
        return '', text
    if value is None:
        return '', text
    message = value.get('ai-message', '')
    details = {key: content for key, content in value.items() if key != 'ai-message'}
    return message, json.dumps(details, ensure_ascii=False, indent=2) if details else ''
