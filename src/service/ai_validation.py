"""Compatibility import for service.ai_support.validation."""

import sys
from .ai_support import validation as _implementation

sys.modules[__name__] = _implementation
