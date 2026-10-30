"""Per-run mappings: destination fields must never trigger a second query."""


def build_mappings(rows, source, content, context_instruction, mode='ai'):
    result = []
    for index, (name, unique, prompt) in enumerate(rows):
        locked = name in {source, content}
        ai = isinstance(unique, str) and unique.startswith('ai:')
        permitted = mode == 'both' or (mode == 'ai' and ai) or (mode == 'dictionary' and not ai)
        mapping = dict(fld_name=name, fld_ord=index, word_checked=name == source,
                       dict_unique='' if locked or not permitted else unique,
                       ignore=locked or not unique or not permitted, ai_prompt=prompt, skip_valued=False)
        if not mapping['ignore'] and ai:
            mapping['ai_prompt'] += '\n' + context_instruction + '\n{{' + source + '}}'
            if content != source:
                mapping['ai_prompt'] += '\n{{' + content + '}}'
        result.append(mapping)
    return result
