"""Build multi-field tasks and validate JSON before any note field is changed."""

import json
import re

from ...translations import text as tr


OUTPUT_INSTRUCTIONS = (
    'Complete every field task in the user request independently. '
    'Return only one JSON object whose keys exactly match the task field names. '
    'Every value must be a non-empty string containing the answer for that field. '
    'Use Markdown inside each string, including tables, lists, bold and newlines when useful. '
    'Escape quotes and newlines correctly for JSON. '
    'Do not return code fences, commentary, extra keys, or nested objects. '
    'These JSON formatting rules take precedence over other output-format requests. '
    'If uncertain, state the uncertainty inside the relevant answer; do not invent facts.'
)


def build_prompt(templates, fields, render):
    if not templates:
        raise ValueError(tr('合并请求没有目标字段。'))
    # Expand only user-authored templates. Field names and inserted field contents
    # must never be interpreted as additional {{Field}} placeholders.
    tasks = {name: render(template, fields) for name, template in templates.items()}
    return json.dumps({'tasks': tasks}, ensure_ascii=False, indent=2)


def parse_fields(text, expected):
    text = text.strip()
    # Tolerate a single enclosing fence, without extracting arbitrary JSON from
    # prose or guessing where an incomplete response was intended to end.
    fence = re.fullmatch(r'```(?:json)?\s*\n(.*?)\n\s*```', text, flags=re.I | re.S)
    if fence:
        text = fence.group(1)

    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError()
            result[key] = value
        return result

    try:
        data = json.loads(text, object_pairs_hook=unique_object)
    except (ValueError, RecursionError):
        raise ValueError(tr('合并回复不是有效的 JSON 对象，原字段内容保留。')) from None
    if not isinstance(data, dict) or set(data) != set(expected):
        raise ValueError(tr('合并回复的字段与请求不一致，原字段内容保留。'))
    if any(not isinstance(value, str) or not value.strip() for value in data.values()):
        raise ValueError(tr('合并回复的每个字段必须是非空文本，原字段内容保留。'))
    return data
