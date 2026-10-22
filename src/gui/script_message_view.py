"""Presentation only: raw replies remain untouched for selection and history."""
from html import escape
from ..utils.markdown import markdown_to_html


def stylesheet(dark):
    background, border = ('#25282c', '#59616b') if dark else ('#f2f4f7', '#c8cdd4')
    return ('p { margin-top: 4px; margin-bottom: 8px; }'
            'pre { white-space: pre-wrap; background-color: %s; padding: 8px; }'
            'code { font-family: monospace; }'
            'th, td { padding: 5px; }'
            '.reply-markdown th { background-color: %s; }'
            '.reply-markdown td, .reply-markdown th { border: 1px solid %s; }'
            'blockquote { margin-left: 12px; color: #89939e; }') % (background, background, border)


def render_body(shown, message='', details=''):
    if not message:
        return '<pre>' + escape(shown) + '</pre>'
    visible_message = shown[:len(message)]
    visible_details = shown[len(message) + 2:] if len(shown) > len(message) + 2 else ''
    markup = markdown_to_html(visible_message).replace('<table>', '<table border="1" cellspacing="0" cellpadding="5">')
    if details and visible_details:
        markup += '<pre>' + escape(visible_details) + '</pre>'
    return '<div class="reply-markdown">' + markup + '</div>'
