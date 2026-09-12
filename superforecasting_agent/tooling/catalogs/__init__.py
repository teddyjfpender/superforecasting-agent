"""Ordered built-in toolset catalog used by the resolver."""

from .aliases import TOOLSETS as ALIASES
from .capabilities import TOOLSETS as CAPABILITIES
from .forecast import TOOLSETS as FORECAST
from .legacy import TOOLSETS as LEGACY

TOOLSETS = {**CAPABILITIES, **FORECAST, **LEGACY, **ALIASES}
