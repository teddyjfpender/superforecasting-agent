from pathlib import Path


def test_tui_finds_bundled_entry_js(tmp_path):
    """_find_bundled_tui finds entry.js bundled in the package."""
    tui_dist = tmp_path / 'superforecasting_agent/runtime' / "tui_dist"
    tui_dist.mkdir(parents=True)
    entry = tui_dist / "entry.js"
    entry.write_text("// bundled TUI", encoding="utf-8")

    from superforecasting_agent.runtime.main import _find_bundled_tui
    result = _find_bundled_tui(runtime_dir=tmp_path / 'superforecasting_agent/runtime')
    assert result is not None
    assert result.name == "entry.js"


def test_tui_returns_none_when_no_bundle(tmp_path):
    """_find_bundled_tui returns None when no bundle exists."""
    from superforecasting_agent.runtime.main import _find_bundled_tui
    result = _find_bundled_tui(runtime_dir=tmp_path / 'superforecasting_agent/runtime')
    assert result is None
