"""Environment reference follows the native package beyond runtime/."""

from scripts.docgen.config_env_doc import _collect


def test_environment_reference_includes_native_tooling(tmp_path):
    module = tmp_path / "superforecasting_agent/tooling/github_auth.py"
    module.parent.mkdir(parents=True)
    module.write_text('import os\nvalue = os.getenv("GITHUB_APP_ID")\n')
    found = _collect(tmp_path)
    assert found["GITHUB_APP_ID"].modules == {"superforecasting_agent.tooling.github_auth"}
