"""Ordered built-in toolset catalog used by the resolver."""

from .capabilities import TOOLSETS as CAPABILITIES
from .forecast import TOOLSETS as FORECAST
from .legacy import TOOLSETS as LEGACY
from .aliases import TOOLSETS as ALIASES

TOOLSETS = {**CAPABILITIES, **FORECAST, **LEGACY, **ALIASES}
