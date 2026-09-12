"""Shared profile configuration snapshots and revision-checked persistence."""

from __future__ import annotations

import copy
import hashlib
import logging
import threading
from pathlib import Path
from typing import Any

import yaml

from superforecasting_agent.storage.files import (
    ConfigSnapshot,
    atomic_roundtrip_yaml_mutate,
    atomic_roundtrip_yaml_update,
    atomic_yaml_write,
    config_revision,
    set_nested,
    yaml_update_lock,
)

logger = logging.getLogger(__name__)


class ProfileConfiguration:
    """Own the host's raw configuration cache; shared storage owns atomic writes.

    Paths are explicit so loading another profile cannot reuse a prior profile's
    cached settings. Callers receive independent revision-bearing snapshots.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._snapshot: ConfigSnapshot | None = None
        self.last_error: str | None = None

    def load(self, path: Path) -> dict:
        path = path.resolve()
        try:
            try:
                contents = path.read_bytes()
            except FileNotFoundError:
                contents = None
            revision = (
                hashlib.sha256(contents).hexdigest() if contents is not None else None
            )
            with self._lock:
                cached = self._snapshot
                if (
                    cached is not None
                    and cached._path == path
                    and cached._revision == revision
                ):
                    self.last_error = None
                    return copy.deepcopy(cached)
            data = (
                yaml.safe_load(contents.decode("utf-8")) if contents is not None else {}
            )
            if data is None:
                data = {}
            if not isinstance(data, dict):
                raise ValueError("Configuration root must be a mapping")
            snapshot = ConfigSnapshot(data)
            snapshot._path, snapshot._revision = path, revision
            with self._lock:
                self._snapshot = copy.deepcopy(snapshot)
                self.last_error = None
            return snapshot
        except Exception as exc:
            with self._lock:
                self.last_error = str(exc)
            logger.warning("Host configuration unavailable at %s: %s", path, exc)
            return {}

    def save(self, path: Path, config: dict) -> None:
        path = path.resolve()
        with yaml_update_lock(path):
            if (
                not isinstance(config, ConfigSnapshot)
                or config._path != path
                or config._revision != config_revision(path)
            ):
                raise ValueError("Configuration changed; reload before saving")
            atomic_yaml_write(path, dict(config))
            config._revision = config_revision(path)
        with self._lock:
            self._snapshot = copy.deepcopy(config)
            self.last_error = None

    def update_many(self, path: Path, changes: dict[str, Any]) -> None:
        """Publish a related set of fields together against the latest contents."""

        def mutate(config: dict) -> None:
            for key, value in changes.items():
                set_nested(config, key, value)

        atomic_roundtrip_yaml_mutate(path, mutate)
        with self._lock:
            self._snapshot = None
            self.last_error = None

    def update(self, path: Path, key: str, value: Any) -> None:
        atomic_roundtrip_yaml_update(path, key, value)
        with self._lock:
            self._snapshot = None
            self.last_error = None


_value_reader = ProfileConfiguration()


def read_configuration(path: Path | None = None) -> dict[str, Any]:
    """Read normalized runtime values without CLI initialization or file writes.

    Returned values are independent and are not revision-bearing persistence
    snapshots. Missing or malformed profiles retain the established defaults;
    the raw reader reports file errors. Ignore-user-config flags apply here too.
    """
    from superforecasting_agent.configuration import resolve_config
    from superforecasting_agent.constants import get_agent_home
    from superforecasting_agent.profile_paths import ignore_user_config_requested

    if ignore_user_config_requested():
        return resolve_config({})
    target = path if path is not None else Path(get_agent_home()) / "config.yaml"
    raw = _value_reader.load(target)
    try:
        return resolve_config(raw)
    except (TypeError, ValueError) as exc:
        logger.warning("Configuration values unavailable at %s: %s", target, exc)
        return resolve_config({})
