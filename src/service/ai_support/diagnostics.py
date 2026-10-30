"""AI logs record operational metadata, never credentials or prompt content."""

import time
import re
import traceback
from contextvars import ContextVar
from uuid import uuid4
from ...utils.logger import logger
from ...translations import text as tr

_request_id = ContextVar('fastcm_ai_request_id', default='-')
_stage = ContextVar('fastcm_ai_stage', default='prepare')


def stage(name):
    _stage.set(name)


def failure_detail(error, fallback='query'):
    labels = {'prepare': tr('准备请求'), 'send': tr('发送请求'), 'response': tr('读取回复'),
              'parse': tr('解析回复'), 'render': tr('转换字段内容'), 'save': tr('保存字段'),
              'query': tr('执行查询')}
    location = 'save' if fallback == 'save' else getattr(error, 'stage', fallback)
    reason = str(error) if getattr(error, 'safe_message', False) else tr('内部错误，请根据日志中的位置检查。')
    detail = '%s · %s · %s' % (labels.get(location, location), getattr(error, 'code', type(error).__name__), reason)
    request = getattr(error, 'request_id', None)
    if request:
        detail += ' · request=' + request
    # Frame locations are useful without exposing arbitrary exception text or locals.
    if not getattr(error, 'safe_message', False) and error.__traceback__:
        frames = traceback.extract_tb(error.__traceback__)[-4:]
        detail += ' · ' + ' > '.join('%s:%s:%s' % (frame.filename.replace('\\', '/').rsplit('/', 1)[-1],
                                                  frame.lineno, frame.name) for frame in frames)
    return detail


def response_metadata(response, secrets=()):
    """Only retain bounded identifiers; never copy free-form server error messages."""
    values = []
    try:
        data = response.json()
        error = data.get('error', {}) if isinstance(data, dict) else {}
        if isinstance(error, dict):
            for name in ('code', 'type', 'param'):
                value = error.get(name)
                if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.\[\]-]{1,100}', value) and not any(
                        secret and secret in value for secret in secrets):
                    values.append('%s=%s' % (name, value))
    except (ValueError, TypeError, AttributeError):
        pass
    return ', '.join(values)


def started(profile):
    _request_id.set(uuid4().hex[:10])
    stage('prepare')
    provider = profile.get('provider', 'custom')
    if provider not in ('openai', 'deepseek', 'gemini', 'claude', 'qwen', 'custom'):
        provider = 'custom'
    mode = profile.get('mode') if profile.get('mode') in ('responses', 'chat', 'messages', 'interactions') else 'unknown'
    skill = profile.get('skill', '')
    logger.info('[AI] request=%s start provider=%s mode=%s skill=%s',
                _request_id.get(), provider, mode, isinstance(skill, str) and bool(skill.strip()))
    return time.monotonic()


def finished(start, result=None, error=None):
    elapsed = time.monotonic() - start
    if error is not None:
        error.request_id = _request_id.get()
        error.stage = _stage.get()
        logger.warning('[AI] request=%s failed duration=%.2fs %s', _request_id.get(), elapsed, failure_detail(error))
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
    response = mode in ('responses', 'messages')
    input_key, output_key = ('input_tokens', 'output_tokens') if response else ('prompt_tokens', 'completion_tokens')
    input_details = value.get('input_tokens_details' if response else 'prompt_tokens_details', {})
    output_details = value.get('output_tokens_details' if response else 'completion_tokens_details', {})
    cached = count(input_details, 'cached_tokens')
    if cached is None:
        cached = count(value, 'prompt_cache_hit_tokens')
    tokens = dict(input=count(value, input_key), output=count(value, output_key),
                  total=count(value, 'total_tokens'), cached=cached,
                  reasoning=count(output_details, 'reasoning_tokens'))
    if mode == 'interactions':
        tokens.update(input=count(value, 'total_input_tokens'), output=count(value, 'total_output_tokens'),
                      cached=count(value, 'total_cached_tokens'), reasoning=count(value, 'total_thought_tokens'))
    logger.info('[AI] request=%s tokens input=%s output=%s total=%s cached=%s reasoning=%s',
                _request_id.get(), *(number if number is not None else 'unavailable' for number in tokens.values()))
    return tokens
