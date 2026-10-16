"""Compatibility import for service.ai_support.keys."""

import sys
from .ai_support import keys as _implementation

sys.modules[__name__] = _implementation
