"""Compatibility alias for shared startup environment loading."""

import sys

from superforecasting_agent import startup_environment

# Preserve mutable credential-origin and sanitizer state across old imports.
sys.modules[__name__] = startup_environment
