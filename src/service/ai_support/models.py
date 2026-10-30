"""Reference model IDs, checked against official catalogs on 2026-10-30.

These are optional suggestions for text generation, not an account-specific
availability list. Users can always enter any model ID their endpoint supports.
"""

MODEL_CATALOG_DATE = '2026-10-30'
MODEL_SOURCES = {
    'openai': 'https://developers.openai.com/api/docs/models/all',
    'deepseek': 'https://api-docs.deepseek.com/api/list-models/',
    'gemini': 'https://ai.google.dev/gemini-api/docs/models',
    'claude': 'https://platform.claude.com/docs/en/models/overview',
    'qwen': 'https://help.aliyun.com/zh/model-studio/model-list-text-generation/',
}
MODEL_SUGGESTIONS = {
    'openai': ('gpt-6.1-sol', 'gpt-6.1-terra', 'gpt-6-astra', 'gpt-6-luna', 'gpt-6-sol',
               'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-5.6-luna', 'gpt-5.5', 'gpt-5.5-pro'),
    'deepseek': ('deepseek-flash', 'deepseek-v4-pro'),
    'gemini': ('gemini-4-argon', 'gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.6-flash', 'gemini-3.1-flash-lite', 'gemini-3-flash-preview',
               'gemini-3.1-pro-preview'),
    'claude': ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5',
               'claude-fable-5-1'),
    'qwen': ('qwen3.8-max', 'qwen3.8-flash', 'qwen3.7-plus', 'qwen3.8-27b', 'qwen3.8-2.4t-a95b', 'qwen3.7-flash', 'qwen3.7-max', 'qwen3.6-plus', 'qwen3.6-flash', 'qwen3.6-27b'),
    'custom': (),
}

# Earlier reference choices remain accessible without crowding the primary list.
OTHER_MODELS = {
    'openai': ('gpt-5.4', 'gpt-5.4-pro', 'gpt-5.4-mini', 'gpt-5.2', 'gpt-5.2-pro', 'gpt-4.1', 'gpt-4o'),
    'deepseek': ('deepseek-v4-flash', 'deepseek-chat', 'deepseek-reasoner'),
    'gemini': ('gemini-2.5-pro', 'gemini-2.5-flash', 'gemini-2.5-flash-lite'),
    'claude': ('claude-opus-4-7', 'claude-sonnet-4-6', 'claude-haiku-4-5'),
    'qwen': ('qwen3.5-plus', 'qwen3.5-flash', 'qwen-plus', 'qwen-max', 'qwen-flash'),
    'custom': (),
}
