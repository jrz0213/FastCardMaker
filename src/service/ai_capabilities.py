"""Compatibility import for service.ai_support.capabilities."""

import sys
from .ai_support import capabilities as _implementation

sys.modules[__name__] = _implementation
