"""Compatibility import for service.ai_support.store."""

import sys
from .ai_support import store as _implementation

sys.modules[__name__] = _implementation
