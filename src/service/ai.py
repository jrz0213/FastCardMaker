"""Text-only AI requests using Responses or Chat Completions protocols."""

from ..translations import text as tr

import re
from copy import deepcopy
from dataclasses import dataclass, field
from html import unescape

import requests
from bs4 import BeautifulSoup

from .ai_config import profile_for, session_key, validate_profile
from .result import QueryResult
from ..utils.ai_format import render as render_output, style_for
from ..context import config
from .ai_limits import AIRequestLimiter
from .ai_support.parameters import parameters_for, endpoint, protocol
from .ai_support import diagnostics
from .ai_support.retry import retry_delay
from .ai_support.batching import OUTPUT_INSTRUCTIONS, build_prompt, parse_fields

_requests_limit = AIRequestLimiter()


@dataclass(frozen=True)
class AIConnection:
    profile: object = field(repr=False)
    key: str = field(repr=False)
    markdown: bool = True
    classes: bool = False


def snapshot_connection(unique, model_id=None):
    profile = profile_for(unique)
    return AIConnection(deepcopy(profile), session_key(profile['id']) if profile else '',
                        bool(getattr(config, 'ai_markdown', True)),
                        bool(style_for(config, model_id).get('enabled', False)))


def _send(address, headers, payload, profile, cancelled):
    retries = profile.get('retries', 2)
    for attempt in range(retries + 1):
        if not _requests_limit.acquire(cancelled=cancelled):
            raise AIError(tr('AI 任务已取消。'), code='cancelled')
        try:
            if cancelled and cancelled():
                raise AIError(tr('AI 任务已取消。'), code='cancelled')
            diagnostics.dispatched(attempt + 1)
            response = requests.post(address, headers=headers, json=payload,
                                     timeout=(profile.get('connect_timeout', 10), profile['timeout']), allow_redirects=False)
            delay = retry_delay(response, attempt, retries)
            if delay is not None:
                diagnostics.retrying(response.status_code, delay, attempt + 2)
                _requests_limit.defer(delay)
        finally:
            _requests_limit.release()
        if delay is None:
            return response


class AIError(ValueError):
    """A safe, user-readable error; never includes headers or response bodies."""

    def __init__(self, message, code='ai_error'):
        super().__init__(message)
        self.code = code


def render_prompt(template, fields):
    def replace(match):
        name = match.group(1).strip()
        if name not in fields:
            raise AIError(tr('提示词引用了不存在的字段：') + name)
        html = str(fields[name] or '')
        html = re.sub(r'<br\s*/?>|</(?:p|div|li)>', '\n', html, flags=re.I)
        return unescape(BeautifulSoup(html, 'html.parser').get_text()).strip()
    if not template or not template.strip():
        raise AIError(tr('请先填写 AI 提示词。'))
    return re.sub(r'\{\{([^{}]+)\}\}', replace, template)


def request_payload(profile, prompt, output_instructions='', history=None):
    mode = protocol(profile)
    data = {'model': profile['model']}
    skill = profile.get('skill', '').strip()
    if output_instructions:
        skill = '\n\n'.join(filter(None, (skill, output_instructions)))
    if mode == 'responses':
        data.update(input=prompt, store=bool(profile.get('responses_store', False)))
        if history:
            data['input'] = list(history) + [{'role': 'user', 'content': prompt}]
        if skill:
            data['instructions'] = skill
    elif mode == 'interactions':
        # Stateless text queries: include the full visible transcript as context.
        # Never fabricate model_output steps without Google's thought signatures.
        if history:
            transcript = '\n\n'.join(str(turn['role']) + ':\n' + str(turn['content']) for turn in history)
            prompt = 'Earlier conversation (context):\n' + transcript + '\n\nCurrent user request:\n' + prompt
        data.update(input=prompt, store=False, stream=False)
        if skill:
            data['system_instruction'] = skill
    elif mode == 'messages':
        data.update(messages=list(history or []) + [{'role': 'user', 'content': prompt}],
                    stream=False, max_tokens=4096)
        if skill:
            data['system'] = skill
    else:
        data.update(messages=list(history or []) + [{'role': 'user', 'content': prompt}],
                    stream=False)
        if skill:
            role = profile.get('skill_role', '')
            if not role:
                role = 'system'
            data['messages'].insert(0, {'role': role, 'content': skill})
    data.update(parameters_for(profile))
    return data


def response_text(data, mode):
    if not isinstance(data, dict):
        raise AIError(tr('AI 返回格式与所选接口模式不一致。'))
    if mode == 'responses':
        if data.get('error') or data.get('status') in ('failed', 'incomplete', 'cancelled', 'queued', 'in_progress'):
            raise AIError(tr('AI 回复未完整生成，请检查回复长度、模型或服务状态。'))
        text = '\n'.join(part['text'] for item in data.get('output', [])
                         if item.get('type') == 'message' and item.get('role', 'assistant') == 'assistant'
                         for part in item.get('content', [])
                         if part.get('type') == 'output_text' and isinstance(part.get('text'), str))
    elif mode == 'interactions':
        if data.get('error') or data.get('status') != 'completed':
            raise AIError(tr('AI 回复未完整生成，请检查回复长度、模型或服务状态。'))
        text = '\n'.join(part['text'] for step in data.get('steps', [])
                         if step.get('type') == 'model_output'
                         for part in step.get('content', [])
                         if part.get('type') == 'text' and isinstance(part.get('text'), str))
    elif mode == 'messages':
        if data.get('type') != 'message' or data.get('stop_reason') not in ('end_turn', 'stop_sequence'):
            raise AIError(tr('AI 回复为空或未完整生成。'))
        text = '\n'.join(part['text'] for part in data.get('content', [])
                         if part.get('type') == 'text' and isinstance(part.get('text'), str))
    else:
        choices = data.get('choices', [])
        if not choices or choices[0].get('finish_reason') in ('length', 'content_filter'):
            raise AIError(tr('AI 回复为空或未完整生成。'))
        content = choices[0].get('message', {}).get('content', '')
        text = content if isinstance(content, str) else '\n'.join(
            part.get('text', '') for part in (content or []) if part.get('type') == 'text')
    if not text.strip():
        raise AIError(tr('AI 未返回可写入的正文。'))
    return text


def query_ai(unique, template, fields, cancelled=None, connection=None):
    start = diagnostics.started((connection.profile if connection is not None else profile_for(unique)) or {})
    try:
        result = _query_ai(unique, template, fields, cancelled, connection)
    except Exception as error:
        diagnostics.finished(start, error=error)
        raise
    diagnostics.finished(start, result=result)
    return result


def _query_ai(unique, template, fields, cancelled=None, connection=None):
    connection = connection or snapshot_connection(unique)
    prompt = render_prompt(template, fields)
    text = _request_text(unique, prompt, cancelled, connection=connection)
    return QueryResult(result=render_output(text, connection.markdown, connection.classes))


def query_ai_many(unique, templates, fields, cancelled=None, connection=None):
    """One paced request per note/profile; parse before rendering each field."""
    connection = connection or snapshot_connection(unique)
    start = diagnostics.started(connection.profile or {})
    try:
        prompt = build_prompt(templates, fields, render_prompt)
        text = _request_text(unique, prompt, cancelled, OUTPUT_INSTRUCTIONS, connection)
        try:
            values = parse_fields(text, templates)
        except ValueError as error:
            raise AIError(str(error), code='structured_output') from None
        result = {name: QueryResult(result=render_output(value, connection.markdown, connection.classes)) for name, value in values.items()}
    except Exception as error:
        diagnostics.finished(start, error=error)
        raise
    diagnostics.finished(start, result=QueryResult(result=''.join(value.result for value in result.values())))
    return result


def request_ai_text(unique, prompt, instructions, cancelled=None, connection=None, history=None):
    """Send literal source data without field interpolation or Markdown conversion."""
    start = diagnostics.started((connection.profile if connection else profile_for(unique)) or {})
    try:
        result = (_request_text(unique, prompt, cancelled, instructions, connection, history=history)
                  if history else _request_text(unique, prompt, cancelled, instructions, connection))
    except Exception as error:
        diagnostics.finished(start, error=error)
        raise
    diagnostics.finished(start, result=QueryResult(result=result))
    return result


def _request_text(unique, prompt, cancelled=None, output_instructions='', connection=None, history=None):
    profile = connection.profile if connection is not None else profile_for(unique)
    if profile is None:
        raise AIError(tr('AI 配置已删除，请重新选择。'))
    validate_profile(profile)
    key = connection.key if connection is not None else session_key(profile['id'])
    if not key:
        raise AIError(tr('未填写 API Key，请打开 AI 设置。'), code='missing_key')
    address = endpoint(profile)
    mode = protocol(profile)
    headers = {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}
    if mode == 'interactions':
        headers = {'x-goog-api-key': key, 'Content-Type': 'application/json'}
    elif mode == 'messages':
        headers = {'x-api-key': key, 'anthropic-version': '2023-06-01', 'Content-Type': 'application/json'}
    payload = request_payload(profile, prompt, output_instructions, history=history)
    try:
        response = _send(address, headers, payload, profile, cancelled)
        if response.status_code != 200:
            status = response.status_code
            messages = {
                401: 'AI 密钥无效或已失效（HTTP 401），请更新 AI 设置中的 Key。',
                403: 'AI 账户没有调用权限（HTTP 403），请检查账户和模型权限。',
                429: 'AI 请求过于频繁或额度不足（HTTP 429），请降低每分钟发送数或检查服务额度。',
            }
            if status in messages:
                message = tr(messages[status])
            elif status >= 500:
                message = tr('AI 服务暂时异常（HTTP %s），请稍后重试。') % status
            else:
                message = tr('AI 请求失败（HTTP %s），请检查地址、密钥、模型和参数。') % status
            raise AIError(message, code='http_%s' % status)
        data = response.json()
        diagnostics.usage(data, mode)
        text = response_text(data, mode)
    except requests.RequestException:
        raise AIError(tr('AI 请求超时或连接失败，请检查网络和 API 地址。'), code='connection') from None
    except (KeyError, TypeError, AttributeError):
        raise AIError(tr('AI 返回格式与所选接口模式不一致。')) from None
    except ValueError as error:
        if isinstance(error, AIError):
            raise
        raise AIError(tr('AI 返回了无效的数据。')) from None
    return text
