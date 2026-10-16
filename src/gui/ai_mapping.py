"""Compatibility import for gui.ai_ui.mapping."""

import sys
from .ai_ui import mapping as _implementation

sys.modules[__name__] = _implementation
