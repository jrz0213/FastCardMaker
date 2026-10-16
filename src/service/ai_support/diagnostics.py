"""AI logs record operational metadata, never credentials or prompt content."""

import time
from contextvars import ContextVar
from uuid import uuid4
from ...utils.logger import logger

_request_id = ContextVar('fastcm_ai_request_id', default='-')


def started(profile):
    _request_id.set(uuid4().hex[:10])
    provider = profile.get('provider', 'custom')
    if provider not in ('openai', 'deepseek', 'gemini', 'claude', 'qwen', 'custom'):
        provider = 'custom'
    mode = 'responses' if profile.get('mode') == 'responses' else 'chat'
    skill = profile.get('skill', '')
    logger.info('[AI] request=%s start provider=%s mode=%s skill=%s',
                _request_id.get(), provider, mode, isinstance(skill, str) and bool(skill.strip()))
    return time.monotonic()


def finished(start, result=None, error=None):
    elapsed = time.monotonic() - start
    if error is not None:
        logger.warning('[AI] request=%s failed duration=%.2fs category=%s', _request_id.get(), elapsed,
                       getattr(error, 'code', type(error).__name__))
    else:
        logger.info('[AI] request=%s complete duration=%.2fs output_chars=%s',
                    _request_id.get(), elapsed, len(result.get('result', '')))


def dispatched(attempt):
    logger.info('[AI] request=%s sent attempt=%s', _request_id.get(), attempt)


def retrying(status, delay, attempt):
    logger.warning('[AI] request=%s retry status=%s delay=%.1fs next_attempt=%s',
                   _request_id.get(), status, delay, attempt)


def usage(data, mode):
    """Log only non-negative integer usage supplied by the provider."""
    value = data.get('usage', {}) if isinstance(data, dict) else {}
    if not isinstance(value, dict):
        value = {}
    def count(mapping, name):
        result = mapping.get(name) if isinstance(mapping, dict) else None
        return result if type(result) is int and result >= 0 else None
    response = mode == 'responses'
    input_key, output_key = ('input_tokens', 'output_tokens') if response else ('prompt_tokens', 'completion_tokens')
    input_details = value.get('input_tokens_details' if response else 'prompt_tokens_details', {})
    output_details = value.get('output_tokens_details' if response else 'completion_tokens_details', {})
    cached = count(input_details, 'cached_tokens')
    if cached is None:
        cached = count(value, 'prompt_cache_hit_tokens')
    tokens = dict(input=count(value, input_key), output=count(value, output_key),
                  total=count(value, 'total_tokens'), cached=cached,
                  reasoning=count(output_details, 'reasoning_tokens'))
    logger.info('[AI] request=%s tokens input=%s output=%s total=%s cached=%s reasoning=%s',
                _request_id.get(), *(number if number is not None else 'unavailable' for number in tokens.values()))
    return tokens
