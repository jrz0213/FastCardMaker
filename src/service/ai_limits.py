"""Compatibility import for service.ai_support.limits."""

import sys
from .ai_support import limits as _implementation

sys.modules[__name__] = _implementation
