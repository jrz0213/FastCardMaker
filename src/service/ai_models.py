"""Compatibility import for service.ai_support.models."""

import sys
from .ai_support import models as _implementation

sys.modules[__name__] = _implementation
