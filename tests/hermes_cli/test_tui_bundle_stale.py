"""_tui_bundle_is_stale: rebuild the working-copy TUI bundle when src outruns dist.

Guards the dev footgun where ``--tui`` runs the prebuilt ``ui-tui/dist/entry.js``
and edits under ``ui-tui/src/**`` are silently ignored until ``npm run build``.
"""

import os
from pathlib import Path

import pytest


@pytest.fixture
def main_mod():
    import hermes_cli.main as m

    return m


def _make_bundle(root: Path, *, bundle_mtime: float, src_mtime: float | None) -> None:
    entry = root / "dist" / "entry.js"
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("console.log('tui')", encoding="utf-8")
    os.utime(entry, (bundle_mtime, bundle_mtime))
    if src_mtime is not None:
        src_file = root / "src" / "entry.tsx"
        src_file.parent.mkdir(parents=True, exist_ok=True)
        src_file.write_text("export {}", encoding="utf-8")
        os.utime(src_file, (src_mtime, src_mtime))


def test_fresh_bundle_not_stale(tmp_path: Path, main_mod) -> None:
    """Bundle newer than its source → not stale."""
    _make_bundle(tmp_path, bundle_mtime=2000, src_mtime=1000)
    assert main_mod._tui_bundle_is_stale(tmp_path) is False


def test_bundle_older_than_src_is_stale(tmp_path: Path, main_mod) -> None:
    """Source edited after the last build → stale."""
    _make_bundle(tmp_path, bundle_mtime=1000, src_mtime=2000)
    assert main_mod._tui_bundle_is_stale(tmp_path) is True


def test_no_src_dir_never_stale(tmp_path: Path, main_mod) -> None:
    """Packaged/nix release (no src/) → shipped bundle is authoritative."""
    _make_bundle(tmp_path, bundle_mtime=1000, src_mtime=None)
    assert main_mod._tui_bundle_is_stale(tmp_path) is False


def test_no_bundle_never_stale(tmp_path: Path, main_mod) -> None:
    """No dist/entry.js at all → nothing to be stale against."""
    src_file = tmp_path / "src" / "entry.tsx"
    src_file.parent.mkdir(parents=True, exist_ok=True)
    src_file.write_text("export {}", encoding="utf-8")
    assert main_mod._tui_bundle_is_stale(tmp_path) is False


def test_newer_tsx_in_subdir_is_stale(tmp_path: Path, main_mod) -> None:
    """A newer *.tsx nested under src/ is detected (rglob)."""
    _make_bundle(tmp_path, bundle_mtime=1000, src_mtime=500)
    nested = tmp_path / "src" / "components" / "Widget.tsx"
    nested.parent.mkdir(parents=True, exist_ok=True)
    nested.write_text("export const W = () => null", encoding="utf-8")
    os.utime(nested, (3000, 3000))
    assert main_mod._tui_bundle_is_stale(tmp_path) is True


def test_newer_build_script_is_stale(tmp_path: Path, main_mod) -> None:
    """A build script newer than the bundle also marks it stale."""
    _make_bundle(tmp_path, bundle_mtime=1000, src_mtime=500)
    build = tmp_path / "scripts" / "build.mjs"
    build.parent.mkdir(parents=True, exist_ok=True)
    build.write_text("// build", encoding="utf-8")
    os.utime(build, (4000, 4000))
    assert main_mod._tui_bundle_is_stale(tmp_path) is True
