"""Reference model IDs, checked against official catalogs on 2026-10-12.

These are optional suggestions for text generation, not an account-specific
availability list. Users can always enter any model ID their endpoint supports.
"""

MODEL_CATALOG_DATE = '2026-10-12'
MODEL_SOURCES = {
    'openai': 'https://developers.openai.com/api/docs/models/all',
    'deepseek': 'https://api-docs.deepseek.com/api/list-models/',
    'gemini': 'https://ai.google.dev/gemini-api/docs/models',
    'claude': 'https://platform.claude.com/docs/en/models/overview',
    'qwen': 'https://help.aliyun.com/zh/model-studio/model-list-text-generation/',
}
MODEL_SUGGESTIONS = {
    'openai': ('gpt-6.1-sol', 'gpt-6-astra', 'gpt-6-luna'),
    'deepseek': ('deepseek-flash', 'deepseek-v4-pro'),
    'gemini': ('gemini-3.8-flash', 'gemini-3.5-flash-lite', 'gemini-3.6-flash',
               'gemini-3.1-pro-preview'),
    'claude': ('claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5',
               'claude-fable-5-1'),
    'qwen': ('qwen3.8-max', 'qwen3.8-flash', 'qwen3.7-plus', 'qwen3.8-27b'),
    'custom': (),
}
