"""Stateless conversation adapters; callers own the selected local history."""
from copy import deepcopy


def _messages(prompt, history):
    return deepcopy(list(history or [])) + [{'role': 'user', 'content': prompt}]


def chat(profile, prompt, instructions, history=None):
    turns = _messages(prompt, history)
    if instructions:
        turns.insert(0, {'role': profile.get('skill_role') or 'system', 'content': instructions})
    return dict(messages=turns, stream=False)


def responses(profile, prompt, instructions, history=None):
    payload = dict(input=_messages(prompt, history) if history else prompt,
                   store=bool(profile.get('responses_store', False)))
    if instructions:
        payload['instructions'] = instructions
    return payload


def messages(profile, prompt, instructions, history=None):
    payload = dict(messages=_messages(prompt, history), stream=False, max_tokens=4096)
    if instructions:
        payload['system'] = instructions
    return payload


ADAPTERS = {'chat': chat, 'responses': responses, 'messages': messages}
