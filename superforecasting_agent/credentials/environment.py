"""Profile-bound credential reads without CLI initialization or mutation."""

from __future__ import annotations

import os
from pathlib import Path

from superforecasting_agent.constants import get_agent_home
from superforecasting_agent.storage.configuration import read_configuration
from superforecasting_agent.storage.environment import read_environment

load_config = read_configuration


def load_env() -> dict[str, str]:
    return read_environment(Path(get_agent_home()) / ".env")


def get_env_value(key: str) -> str | None:
    if key in os.environ:
        return os.environ[key]
    return load_env().get(key)
