#!/usr/bin/env python3
"""Compatibility entrypoint; agent implementation is owned by agent.runtime.

Module identity is retained so legacy imports and patches address the same
runtime state as fork-native callers.
"""
import superforecasting_agent.bootstrap  # noqa: F401

import sys
from agent import runtime

if __name__ == "__main__":
    import fire
    fire.Fire(runtime.main)
else:
    sys.modules[__name__] = runtime
