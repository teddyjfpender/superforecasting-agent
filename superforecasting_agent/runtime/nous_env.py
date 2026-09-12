"""Compatibility alias for shared Nous environment policy."""

import sys
from superforecasting_agent.configuration import nous_env
sys.modules[__name__] = nous_env
