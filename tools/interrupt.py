"""Compatibility imports for the shared per-thread cancellation owner."""

from superforecasting_agent.tooling.interrupts import (
    _interrupt_event as _interrupt_event,
    _interrupted_threads as _interrupted_threads,
    _lock as _lock,
    is_interrupted as is_interrupted,
    set_interrupt as set_interrupt,
)
