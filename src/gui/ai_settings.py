"""Compatibility import for gui.ai_ui.settings."""

import sys
from .ai_ui import settings as _implementation

sys.modules[__name__] = _implementation
