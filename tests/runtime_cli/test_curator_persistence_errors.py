"""Native and standalone curator commands agree when persistence fails."""

import pytest

from agent import curator
from superforecasting_agent.runtime import curator as commands
from superforecasting_agent.storage import files


@pytest.mark.parametrize('action', ['pause', 'resume'])
@pytest.mark.parametrize('interface', ['standalone', 'native'])
def test_publication_failure_returns_nonzero_without_success(tmp_path, monkeypatch, action, interface):
    path = tmp_path / '.curator_state'
    monkeypatch.setattr(curator, '_state_file', lambda: path)
    curator.save_state({'paused': action == 'resume'})
    previous = path.read_bytes()
    def fail(*args):
        raise OSError('disk publication failed')
    monkeypatch.setattr(files, 'atomic_replace', fail)
    if interface == 'native':
        code, output = commands.command_output(action)
    else:
        lines = []
        code = commands.cli_main([action], emit=lambda value, **kwargs: lines.append(value))
        output = '\n'.join(lines)
    assert code == 1
    assert 'disk publication failed' in output
    assert 'curator: paused' not in output
    assert 'curator: resumed' not in output
    assert path.read_bytes() == previous
