"""CLI and gateway aliases share argument, precedence and cycle behavior."""

import pytest

from superforecasting_agent.runtime.commands import expand_quick_alias


def test_nested_alias_preserves_arguments_and_builtin_precedence():
    aliases = {
        "desk-model": {"type": "alias", "target": "fast-model --provider custom"},
        "fast-model": {"type": "alias", "target": "/model CaseSensitiveModel"},
        "model": {"type": "alias", "target": "/quit"},
    }
    assert expand_quick_alias("/DESK-MODEL --base-url https://Host/Path", aliases) == (
        "/model CaseSensitiveModel --provider custom --base-url https://Host/Path"
    )
    assert expand_quick_alias("/model Original", aliases) == "/model Original"


@pytest.mark.parametrize("aliases", [
    {"a": {"type": "alias", "target": "a"}},
    {"a": {"type": "alias", "target": "b"}, "b": {"type": "alias", "target": "a"}},
])
def test_alias_cycles_fail_before_dispatch(aliases):
    with pytest.raises(ValueError, match="cycle"):
        expand_quick_alias("/a", aliases)


def test_invalid_entries_and_empty_target():
    assert expand_quick_alias("/a Arg", {"a": None}) == "/a Arg"
    assert expand_quick_alias("/a Arg", {"a": {"type": "exec"}}) == "/a Arg"
    with pytest.raises(ValueError, match="no target"):
        expand_quick_alias("/a", {"a": {"type": "alias"}})
