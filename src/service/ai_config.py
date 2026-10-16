"""Compatibility import for service.ai_support.config."""

import sys
from .ai_support import config as _implementation

sys.modules[__name__] = _implementation
