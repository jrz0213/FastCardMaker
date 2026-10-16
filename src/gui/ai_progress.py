"""Compatibility import for gui.ai_ui.progress."""

import sys
from .ai_ui import progress as _implementation

sys.modules[__name__] = _implementation
