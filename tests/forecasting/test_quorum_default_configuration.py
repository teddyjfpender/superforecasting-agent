"""Quorum enablement and applicability are one validated policy update."""
import pytest
import yaml

from forecasting.cli.quorum_panel import _quorum_default


@pytest.fixture
def profile(tmp_path, monkeypatch):
    from superforecasting_agent import constants
    monkeypatch.setattr(constants, 'get_agent_home', lambda: tmp_path)
    for name in ('SUPERFORECASTING_AGENT_MANAGED', 'FORECAST_MANAGED', 'HERMES_MANAGED'):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / 'config.yaml'
    path.write_text('quorum:\n  default_enabled: false\n  default_scope: high_impact\ndisplay:\n  skin: mono\n', encoding='utf-8')
    return path


def test_invalid_scope_does_not_partially_enable_quorum(profile, capsys):
    before = profile.read_bytes()
    with pytest.raises(SystemExit, match='scope must be'):
        _quorum_default(['on'], scope='wrong')
    assert profile.read_bytes() == before
    assert '✓' not in capsys.readouterr().out


def test_managed_refusal_does_not_report_success(profile, monkeypatch, capsys):
    monkeypatch.setenv('SUPERFORECASTING_AGENT_MANAGED', 'homebrew')
    before = profile.read_bytes()
    _quorum_default(['on'], scope='always')
    assert profile.read_bytes() == before
    out = capsys.readouterr().out
    assert 'managed by Homebrew' in out
    assert '✓' not in out


def test_default_policy_publishes_both_fields_together(profile, monkeypatch, capsys):
    from contextlib import contextmanager
    from superforecasting_agent.storage import files
    original = files._atomic_text_writer
    writes = []
    @contextmanager
    def capture(path):
        with original(path) as stream:
            yield stream
        writes.append(yaml.safe_load(profile.read_text(encoding='utf-8')))
    monkeypatch.setattr(files, '_atomic_text_writer', capture)
    _quorum_default(['ON'], scope='first_only')
    assert len(writes) == 1
    assert writes[0]['quorum'] == {'default_enabled': True, 'default_scope': 'first_only'}
    assert writes[0]['display']['skin'] == 'mono'
    assert 'enabled' in capsys.readouterr().out
