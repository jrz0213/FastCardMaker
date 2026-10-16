"""Prevent AI prompts from depending on AI-generated note fields."""

from ...translations import text as tr

import re

from .config import is_ai


def validate_ai_references(template, mappings, field_names):
    ai_fields = set()
    for index, mapping in enumerate(mappings):
        if mapping.get('word_checked') or not is_ai(mapping.get('dict_unique')):
            continue
        ordinal = mapping.get('fld_ord', index)
        if 0 <= ordinal < len(field_names):
            ai_fields.add(field_names[ordinal])
    referenced = {name.strip() for name in re.findall(r'\{\{([^{}]+)\}\}', template or '')}
    forbidden = sorted(referenced & ai_fields)
    if forbidden:
        raise ValueError(tr('AI 提示词不能引用 AI 输出字段：') + '、'.join(forbidden) +
                         tr('。请改为引用普通字段（包括单词来源字段）。'))


def validate_ai_mappings(mappings, field_names):
    for mapping in mappings:
        if not mapping.get('ignore', False) and not mapping.get('word_checked') and is_ai(mapping.get('dict_unique')):
            validate_ai_references(mapping.get('ai_prompt', ''), mappings, field_names)
