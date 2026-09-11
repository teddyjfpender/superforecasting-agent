"""Compatibility alias for the shared platform registration owner."""
import sys
from superforecasting_agent import platform_registry as _owner

sys.modules[__name__] = _owner
