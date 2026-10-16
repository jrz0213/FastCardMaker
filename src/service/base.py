"""Compatibility entry point for existing dictionary scripts.

Implementations live in the core, web, local, mdx, and stardict modules.
Keep importing from this module in external dictionary scripts."""

from .result import QueryResult
from .helpers import (
    register, export, copy_static_file, with_styles, parse_html,
    service_wrap, get_hex_name, sanitize_to_safe_encoding,
)
from .core import Service
from .web import WebService
from .local import LocalService
from .mdx import MdxService
from .stardict import StardictService


__all__ = [
    'register', 'export', 'copy_static_file', 'with_styles', 'parse_html', 'service_wrap', 'get_hex_name',
    'Service', 'WebService', 'LocalService', 'MdxService', 'StardictService', 'QueryResult'
]
