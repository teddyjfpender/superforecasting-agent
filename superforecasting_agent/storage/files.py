"""Atomic JSON/YAML writes that preserve symlinks and file permissions."""

import json
import logging
import os
import stat
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TextIO, Union

import yaml

logger = logging.getLogger(__name__)


# ponytail: serialize YAML writes globally; use per-path locks if contention warrants it.
_YAML_LOCK = threading.RLock()
_YAML_LOCK_HOLDERS = threading.local()


@contextmanager
def yaml_update_lock(path):
    """Serialize read-modify-write across threads, processes and symlink aliases."""
    from .locking import file_lock
    target = Path(path).resolve()
    with _YAML_LOCK:
        holders = getattr(_YAML_LOCK_HOLDERS, 'paths', None)
        if holders is None:
            holders = _YAML_LOCK_HOLDERS.paths = {}
        holder = holders.setdefault(str(target), threading.local())
        with file_lock(target.with_name(target.name + '.lock'), holder, 10,
                       'Timed out waiting for configuration writer'):
            yield


def set_nested(config, dotted_key: str, value):
    """Set a value at an arbitrarily nested dotted key path.

    Supports both dict and list navigation:
      _set_nested(c, "a.b.c", 1)     → c["a"]["b"]["c"] = 1
      _set_nested(c, "a.0.b", 1)     → c["a"][0]["b"] = 1
      _set_nested(c, "providers.1", "x") → c["providers"][1] = "x"

    Intermediate dicts are created on demand.  List indices are parsed
    from numeric path segments; the referenced index must already exist
    (we do not grow lists — the user is navigating into structure they
    wrote themselves).  If a segment targets a non-container leaf
    (scalar), the leaf is replaced with a fresh dict so the write can
    proceed — this preserves the pre-existing behavior for bare scalar
    overrides (e.g. setting ``a.b.c`` where ``a.b`` was previously a
    string).

    Guards against #17876: before this fix the code unconditionally
    replaced any non-dict value (including lists) with ``{}``, silently
    destroying list-typed config like ``custom_providers`` whenever a
    caller used an indexed path.
    """
    parts = dotted_key.split(".")
    current = config
    for part in parts[:-1]:
        if isinstance(current, list):
            try:
                idx = int(part)
            except (TypeError, ValueError):
                raise TypeError(
                    f"Cannot navigate into list at key {dotted_key!r}: "
                    f"segment {part!r} is not a numeric index"
                )
            current = current[idx]
        elif isinstance(current, dict):
            existing = current.get(part)
            # Preserve dicts and lists; replace missing/scalar with a fresh dict.
            if part not in current or not isinstance(existing, (dict, list)):
                current[part] = {}
            current = current[part]
        else:
            raise TypeError(
                f"Cannot navigate into {type(current).__name__} at key {dotted_key!r}"
            )
    last = parts[-1]
    if isinstance(current, list):
        current[int(last)] = value
    else:
        current[last] = value


def _preserve_file_mode(path: Path) -> "int | None":
    """Capture the permission bits of *path* if it exists, else ``None``."""
    try:
        return stat.S_IMODE(path.stat().st_mode) if path.exists() else None
    except OSError:
        return None


def _restore_file_mode(path: Path, mode: "int | None") -> None:
    """Re-apply *mode* to *path* after an atomic replace.

    ``tempfile.mkstemp`` creates files with 0o600 (owner-only).  After
    ``os.replace`` swaps the temp file into place the target inherits
    those restrictive permissions, breaking Docker / NAS volume mounts
    that rely on broader permissions set by the user.  Calling this
    right after ``os.replace`` restores the original permissions.
    """
    if mode is None:
        return
    try:
        os.chmod(path, mode)
    except OSError:
        pass


def atomic_replace(tmp_path: Union[str, Path], target: Union[str, Path]) -> str:
    """Atomically move *tmp_path* onto *target*, preserving symlinks.

    ``os.replace(tmp, target)`` atomically swaps ``tmp`` into place at
    ``target``.  When ``target`` is a symlink, the symlink itself is
    replaced with a regular file — silently detaching managed deployments
    that symlink ``config.yaml`` / ``SOUL.md`` / ``auth.json`` etc. from
    ``~/.hermes/`` to a git-tracked profile package or dotfiles repo
    (GitHub #16743).

    This helper resolves the symlink first so ``os.replace`` writes to
    the real file in-place while the symlink survives.  For non-symlink
    and non-existent paths the behavior is identical to a plain
    ``os.replace`` call.

    Returns the resolved real path used for the replace, so callers that
    need to re-apply permissions can target it instead of the symlink.
    """
    target_str = str(target)
    real_path = (
        os.path.realpath(target_str) if os.path.islink(target_str) else target_str
    )
    os.replace(str(tmp_path), real_path)
    return real_path


@contextmanager
def _atomic_text_writer(path: Union[str, Path]) -> Iterator[TextIO]:
    """Commit a complete text write, preserving links and permissions on success."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    original_mode = _preserve_file_mode(path)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=f".{path.stem}_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            yield f
            f.flush()
            os.fsync(f.fileno())
        real_path = atomic_replace(tmp_path, path)
        _restore_file_mode(real_path, original_mode)
    except BaseException:
        # Cleanup also applies to KeyboardInterrupt and SystemExit.
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_json_write(
    path: Union[str, Path],
    data: Any,
    *,
    indent: int = 2,
    **dump_kwargs: Any,
) -> None:
    """Write JSON data to a file atomically.

    Uses temp file + fsync + os.replace to ensure the target file is never
    left in a partially-written state. If the process crashes mid-write,
    the previous version of the file remains intact.

    Args:
        path: Target file path (will be created or overwritten).
        data: JSON-serializable data to write.
        indent: JSON indentation (default 2).
        **dump_kwargs: Additional keyword args forwarded to json.dump(), such
            as default=str for non-native types.
    """

    with _atomic_text_writer(path) as f:
        json.dump(
            data,
            f,
            indent=indent,
            ensure_ascii=False,
            **dump_kwargs,
        )


def atomic_yaml_write(
    path: Union[str, Path],
    data: Any,
    *,
    default_flow_style: bool = False,
    sort_keys: bool = False,
    extra_content: str | None = None,
) -> None:
    """Write YAML data to a file atomically.

    Uses temp file + fsync + os.replace to ensure the target file is never
    left in a partially-written state.  If the process crashes mid-write,
    the previous version of the file remains intact.

    Args:
        path: Target file path (will be created or overwritten).
        data: YAML-serializable data to write.
        default_flow_style: YAML flow style (default False).
        sort_keys: Whether to sort dict keys (default False).
        extra_content: Optional string to append after the YAML dump
            (e.g. commented-out sections for user reference).
    """

    with _atomic_text_writer(path) as f:
        yaml.dump(data, f, default_flow_style=default_flow_style, sort_keys=sort_keys)
        if extra_content:
            f.write(extra_content)


def _roundtrip_codec():
    """Keep YAML 1.2 writers compatible with the application's YAML 1.1 readers."""
    from ruamel.yaml import YAML
    from ruamel.yaml.representer import RoundTripRepresenter

    class ConfigRepresenter(RoundTripRepresenter):
        def represent_str(self, value):
            style = '"' if value.lower() in {'on', 'off', 'yes', 'no'} else None
            return self.represent_scalar('tag:yaml.org,2002:str', value, style=style)

    ConfigRepresenter.add_representer(str, ConfigRepresenter.represent_str)
    codec = YAML(typ="rt")
    codec.Representer = ConfigRepresenter
    codec.version = (1, 1)  # read existing booleans like the application loaders
    codec.preserve_quotes = True
    codec.allow_unicode = True
    return codec


def atomic_roundtrip_yaml_update(
    path: Union[str, Path],
    key_path: str,
    value: Any,
) -> None:
    """Update one dotted YAML key while preserving comments and readable text.

    This is intentionally narrower than :func:`atomic_yaml_write`: it is for
    user-edited config files where comments, ordering, quoting, and Unicode
    should survive a single setting mutation.  Writes still use the same temp
    file + fsync + atomic replace pattern.
    """
    with yaml_update_lock(path):
        try:
            from ruamel.yaml import YAML
            from ruamel.yaml.comments import CommentedMap
        except ModuleNotFoundError:
            _atomic_yaml_update_without_ruamel(path, key_path, value)
            return

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)

        yaml_rt = _roundtrip_codec()
        yaml_rt.preserve_quotes = True
        yaml_rt.allow_unicode = True
        yaml_rt.default_flow_style = False
        yaml_rt.indent(mapping=2, sequence=4, offset=2)

        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                config = yaml_rt.load(f)
                if config is None:
                    config = CommentedMap()
        else:
            config = CommentedMap()

        if not isinstance(config, dict):
            raise ValueError("configuration root must be a mapping")

        set_nested(config, key_path, value)

        with _atomic_text_writer(path) as f:
            yaml_rt.version = None  # avoid introducing a YAML directive
            yaml_rt.dump(config, f)


def atomic_roundtrip_yaml_mutate(path, mutate):
    """Apply a compound edit to the latest mapping under the shared writer lock."""
    path = Path(path)
    with yaml_update_lock(path):
        try:
            from ruamel.yaml import YAML
            codec = _roundtrip_codec()
            codec.preserve_quotes = True
            codec.allow_unicode = True
        except ImportError:
            codec = None
        raw = path.read_text(encoding="utf-8") if path.exists() else ""
        config = codec.load(raw) if codec else yaml.safe_load(raw)
        if config is None:
            config = {}
        if not isinstance(config, dict):
            raise ValueError("configuration root must be a mapping")
        mutate(config)
        with _atomic_text_writer(path) as stream:
            if codec:
                codec.version = None
                codec.dump(config, stream)
            else:
                yaml.safe_dump(config, stream, allow_unicode=True, sort_keys=False)


def _yaml_inline_scalar(value: Any) -> str:
    dumped = yaml.safe_dump(
        value,
        allow_unicode=True,
        default_flow_style=True,
        sort_keys=False,
    ).strip()
    if dumped.endswith("\n..."):
        dumped = dumped[:-4].rstrip()
    return dumped


def _replace_existing_yaml_scalar_line(
    text: str, key_path: str, value: Any
) -> str | None:
    keys = key_path.split(".")
    stack: list[tuple[int, str]] = []
    lines = text.splitlines(keepends=True)

    for idx, line in enumerate(lines):
        body = line.rstrip("\n")
        if not body.strip() or body.lstrip().startswith("#"):
            continue
        leading = len(body) - len(body.lstrip(" "))
        stripped = body.strip()
        if ":" not in stripped:
            continue
        key, rest = stripped.split(":", 1)
        key = key.strip().strip("'\"")
        if not key:
            continue

        while stack and leading <= stack[-1][0]:
            stack.pop()
        current_path = [item[1] for item in stack] + [key]
        if current_path == keys:
            newline = "\n" if line.endswith("\n") else ""
            inline_comment = ""
            rest_text = rest.rstrip()
            if " #" in rest_text:
                inline_comment = " #" + rest_text.split(" #", 1)[1]
            lines[idx] = (
                f"{' ' * leading}{key}: {_yaml_inline_scalar(value)}{inline_comment}{newline}"
            )
            return "".join(lines)
        if rest.strip() == "":
            stack.append((leading, key))
    return None


def _atomic_yaml_update_without_ruamel(
    path: Union[str, Path],
    key_path: str,
    value: Any,
) -> None:
    """Best-effort config update when ruamel.yaml is unavailable.

    Existing scalar lines are replaced in-place so simple user comments survive;
    new keys fall back to PyYAML serialization.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        original_text = path.read_text(encoding="utf-8")
        patched = _replace_existing_yaml_scalar_line(original_text, key_path, value)
        if patched is not None:
            with _atomic_text_writer(path) as f:
                f.write(patched)
            return
        config = yaml.safe_load(original_text)
        if config is None:
            config = {}
    else:
        config = {}

    if not isinstance(config, dict):
        raise ValueError("configuration root must be a mapping")

    set_nested(config, key_path, value)
    atomic_yaml_write(path, config, sort_keys=False)


def safe_json_loads(text: str, default: Any = None) -> Any:
    """Parse JSON, returning *default* on any parse error.

    Replaces the ``try: json.loads(x) except (JSONDecodeError, TypeError)``
    pattern duplicated across display.py, anthropic_adapter.py,
    auxiliary_client.py, and others.
    """
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default
