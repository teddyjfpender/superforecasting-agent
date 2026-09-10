"""Atomic JSON/YAML writes that preserve symlinks and file permissions."""

import json
import logging
import os
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, TextIO, Union

import yaml

logger = logging.getLogger(__name__)


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
    try:
        from ruamel.yaml import YAML
        from ruamel.yaml.comments import CommentedMap
    except ModuleNotFoundError:
        _atomic_yaml_update_without_ruamel(path, key_path, value)
        return

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    yaml_rt = YAML(typ="rt")
    yaml_rt.preserve_quotes = True
    yaml_rt.allow_unicode = True
    yaml_rt.default_flow_style = False
    yaml_rt.indent(mapping=2, sequence=4, offset=2)

    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            config = yaml_rt.load(f) or CommentedMap()
    else:
        config = CommentedMap()

    if not isinstance(config, CommentedMap):
        config = CommentedMap(config)

    current = config
    keys = key_path.split(".")
    for key in keys[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, CommentedMap):
            next_value = CommentedMap()
            current[key] = next_value
        current = next_value
    current[keys[-1]] = value

    with _atomic_text_writer(path) as f:
        yaml_rt.dump(config, f)


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
        config = yaml.safe_load(original_text) or {}
    else:
        config = {}

    if not isinstance(config, dict):
        config = {}

    current = config
    keys = key_path.split(".")
    for key in keys[:-1]:
        next_value = current.get(key)
        if not isinstance(next_value, dict):
            next_value = {}
            current[key] = next_value
        current = next_value
    current[keys[-1]] = value
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
