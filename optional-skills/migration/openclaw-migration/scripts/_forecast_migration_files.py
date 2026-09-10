"""File and input-value helpers for standalone OpenClaw migration."""

from __future__ import annotations

import hashlib
import re
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

try:
    import yaml
except Exception:  # pragma: no cover - handled at runtime
    yaml = None


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def resolve_secret_input(value: Any, env: Optional[Dict[str, str]] = None) -> Optional[str]:
    """Resolve an OpenClaw SecretInput value to a plain string.

    SecretInput can be:
    - A plain string: "sk-..."
    - An env template: "${OPENROUTER_API_KEY}"
    - A SecretRef object: {"source": "env", "id": "OPENROUTER_API_KEY"}
    """
    if isinstance(value, str):
        # Check for env template: "${VAR_NAME}"
        m = re.match(r"^\$\{(\w+)\}$", value.strip())
        if m and env:
            return env.get(m.group(1), "").strip() or None
        return value.strip() or None
    if isinstance(value, dict):
        source = value.get("source", "")
        ref_id = value.get("id", "")
        if source == "env" and ref_id and env:
            return env.get(ref_id, "").strip() or None
        # File/exec sources can't be resolved here — return None
    return None


def load_yaml_file(path: Path) -> Dict[str, Any]:
    if yaml is None or not path.exists():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def dump_yaml_file(path: Path, data: Dict[str, Any]) -> None:
    if yaml is None:
        raise RuntimeError("PyYAML is required to update Superforecasting Agent config.yaml")
    ensure_parent(path)
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=False),
        encoding="utf-8",
    )


def parse_env_file(path: Path) -> Dict[str, str]:
    if not path.exists():
        return {}
    data: Dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        data[key.strip()] = value.strip()
    return data


def save_env_file(path: Path, data: Dict[str, str]) -> None:
    ensure_parent(path)
    lines = [f"{key}={value}" for key, value in data.items()]
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def backup_existing(path: Path, backup_root: Path) -> Optional[Path]:
    if not path.exists():
        return None
    rel = Path(*path.parts[1:]) if path.is_absolute() and len(path.parts) > 1 else path
    dest = backup_root / rel
    ensure_parent(dest)
    if path.is_dir():
        shutil.copytree(path, dest, dirs_exist_ok=True)
    else:
        shutil.copy2(path, dest)
    return dest


def relative_label(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)
