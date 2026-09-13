"""Remote prerequisites use the same Node WebSocket flags as the real launcher."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def launcher(monkeypatch):
    path = Path(__file__).resolve().parents[2] / 'products/tui/superforecasting_agent_tui/__init__.py'
    spec = importlib.util.spec_from_file_location('standalone_fixture', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module.importlib.metadata, 'version', lambda _: '0.1.0')
    monkeypatch.setattr(module.shutil, 'which', lambda _: '/fixture/node')
    monkeypatch.setattr(module, 'bundle_path', lambda: path)
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *a, **kw: 'v20.19.2\n')
    return module


@pytest.mark.parametrize('check', [False, True])
def test_remote_launch_enables_node20_websocket(launcher, monkeypatch, check):
    monkeypatch.setattr('sys.argv', ['tui', '--gateway-url', 'ws://localhost:1'] + (['--check'] if check else []))
    probes, launches = [], []
    def probe(argv, **kwargs):
        probes.append(argv)
        return SimpleNamespace(returncode=0)
    def launch(argv, **kwargs):
        launches.append(argv)
        return 0
    monkeypatch.setattr(launcher.subprocess, 'run', probe)
    monkeypatch.setattr(launcher.subprocess, 'call', launch)
    assert launcher.main() == 0
    assert probes[0][:2] == ['/fixture/node', '--experimental-websocket']
    assert len(launches) == (0 if check else 1)
    if launches:
        assert launches[0][:2] == probes[0][:2]


def test_missing_websocket_fails_before_screen_launch(launcher, monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['tui', '--gateway-url', 'ws://localhost:1', '--check'])
    monkeypatch.setattr(launcher.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(SystemExit) as exc:
        launcher.main()
    assert exc.value.code == 2
    assert 'cannot provide WebSocket support' in capsys.readouterr().err
