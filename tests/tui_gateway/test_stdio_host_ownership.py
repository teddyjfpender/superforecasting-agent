"""Stdio redirection belongs to the command-pipe host, not server imports."""
import io
import subprocess
import sys

import pytest


def test_importing_embedded_rpc_server_preserves_stdout():
    code = 'import sys; before = sys.stdout; from tui_gateway import server; assert sys.stdout is before; print("stdout-preserved")'
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stderr
    assert 'stdout-preserved' in result.stdout


@pytest.mark.parametrize('http', [False, True])
@pytest.mark.parametrize('fail', [False, True])
def test_entry_owns_and_restores_stdio_streams(monkeypatch, http, fail):
    from tui_gateway import entry, server
    output, errors, protocol = io.StringIO(), io.StringIO(), io.StringIO()
    monkeypatch.setattr(sys, 'stdout', output)
    monkeypatch.setattr(sys, 'stderr', errors)
    monkeypatch.setattr(server, '_real_stdout', protocol)
    monkeypatch.setattr(sys, 'argv', ['gateway', '--http'] if http else ['gateway'])
    def run(*args):
        print('ordinary-output')
        if http:
            assert sys.stdout is output
            assert server._real_stdout is protocol
        else:
            assert sys.stdout is errors
            assert server._real_stdout is output
        if fail:
            raise RuntimeError('injected failure')
    monkeypatch.setattr(entry, '_run_stdio', run)
    monkeypatch.setattr(entry, '_run_http', run)
    if fail:
        with pytest.raises(RuntimeError, match='injected failure'):
            entry.main()
    else:
        entry.main()
    assert sys.stdout is output
    assert server._real_stdout is protocol
    assert ('ordinary-output' in output.getvalue()) is http
    assert ('ordinary-output' in errors.getvalue()) is not http
