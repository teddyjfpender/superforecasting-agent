"""Compatibility alias for the shared runtime session context.

Both import paths must expose the same ContextVars and module state.
"""
import sys
from superforecasting_agent import session_context as _owner

sys.modules[__name__] = _owner
