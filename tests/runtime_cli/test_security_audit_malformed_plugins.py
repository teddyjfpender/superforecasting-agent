"""Malformed plugin metadata must not prevent auditing valid plugins."""

import pytest

from superforecasting_agent.runtime import security_audit


@pytest.mark.parametrize("project", ['"invalid"', '123', '["invalid"]', 'true'])
def test_invalid_project_table_does_not_abort_component_discovery(tmp_path, project):
    invalid = tmp_path / "plugins/a-invalid"
    invalid.mkdir(parents=True)
    (invalid / "pyproject.toml").write_text(f"project = {project}\n")
    valid = tmp_path / "plugins/b-valid"
    valid.mkdir(parents=True)
    (valid / "requirements.txt").write_text("fixture-package==1.2.3\n")

    components = security_audit._discover_plugins(tmp_path)

    assert components == [security_audit.Component(
        name="fixture-package", version="1.2.3", ecosystem="PyPI", source="plugin:b-valid",
    )]
