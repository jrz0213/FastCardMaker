"""Shared UI and request rules for text-only compatible APIs."""

from ...translations import text as tr

ALL_EFFORTS = ('', 'none', 'minimal', 'low', 'medium', 'high', 'xhigh', 'max')


def capabilities(profile):
    provider = profile.get('provider', 'custom')
    mode = profile.get('mode', 'responses')
    model = profile.get('model', '').lower()
    effort = profile.get('reasoning', 'none')
    values = ALL_EFFORTS
    reasoning_visible = True
    temperature_visible = True
    hint = (tr('Responses：按强度控制思考。') if mode == 'responses'
            else tr('Chat Completions：思考强度由兼容接口支持范围决定。'))
    if provider == 'deepseek':
        values = ('', 'none', 'low', 'high', 'max')
        temperature_visible = effort == 'none'
        hint = (tr('none 关闭思考；启用思考时不发送温度。') +
                (tr('Responses：按强度控制思考。') if mode == 'responses'
                 else tr('Chat：支持思考开关与强度选择。')))
    elif provider == 'gemini' and mode == 'chat':
        values = ('', 'none', 'minimal', 'low', 'medium', 'high')
        if model.startswith('gemini-3') or model.startswith('gemini-2.5-pro'):
            values = tuple(value for value in values if value != 'none')
            hint = tr('该 Gemini 模型不能关闭思考，请选择默认、minimal、low、medium 或 high。')
        else:
            hint = tr('Gemini Chat 支持默认、none、minimal、low、medium、high，具体取决于模型。')
    elif provider == 'claude' and mode == 'chat':
        values = ('', 'none')
        reasoning_visible = not model.startswith(('claude-opus-5-5', 'claude-sonnet-5-5',
                                                 'claude-fable-5', 'claude-mythos-5',
                                                 'claude-mythos-preview'))
        temperature_visible = False
        hint = (tr('Claude Chat 只提供思考开关；none 关闭思考，温度使用模型默认值。')
                if reasoning_visible else
                tr('该 Claude 模型不能关闭思考；Chat 兼容接口使用模型默认思考与温度。'))
    elif provider == 'openai' and model.startswith('gpt-6'):
        values = ('', 'none', 'low', 'medium', 'high', 'xhigh', 'max')
        if model.startswith(('gpt-6.1-sol', 'gpt-6-astra')):
            values = tuple(value for value in values if value != 'none')
            hint += tr(' 该模型不能关闭思考，请选择 low 或更高强度。')
        temperature_visible = effort == 'none' and 'none' in values
        if not temperature_visible:
            hint += tr(' 思考模式下不发送温度。')
    if provider in ('gemini', 'claude') and mode == 'responses':
        hint += tr(' 该厂商官方预设地址使用 Chat；Responses 需填写支持它的兼容服务地址。')
    if reasoning_visible and effort not in values:
        hint += tr(' 当前保存的思考选项不受支持，请重新选择。')
    return dict(efforts=values, reasoning_visible=reasoning_visible,
                temperature_visible=temperature_visible, hint=hint,
                store_visible=mode == 'responses' and provider in ('openai', 'custom'),
                skill_role_visible=mode == 'chat')
