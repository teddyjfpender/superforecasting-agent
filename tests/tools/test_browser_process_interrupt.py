"""Interrupted browser command waits must reap their actual child processes."""

import subprocess
import sys

import pytest

import tools.browser_tool as browser


@pytest.mark.parametrize('route', ['primary', 'chrome_fallback'])
@pytest.mark.parametrize('failure', ['interrupt', 'unexpected_timeout', 'command_timeout'])
def test_interrupted_wait_reaps_child(monkeypatch, tmp_path, route, failure):
    original_popen = subprocess.Popen
    children = []
    error = {
        'interrupt': KeyboardInterrupt(),
        'unexpected_timeout': TimeoutError('fixture interrupted wait'),
        'command_timeout': subprocess.TimeoutExpired('fixture-browser', 1),
    }[failure]

    def spawn_fixture(_argv, **kwargs):
        first = not children
        program = 'import time; time.sleep(60)' if first else 'print(\'{"success":true,"data":{}}\')'
        child = original_popen([sys.executable, '-c', program], **kwargs)
        wait = child.wait
        children.append((child, wait))
        if first:
            interrupted = False
            def interrupt_once(timeout=None):
                nonlocal interrupted
                if not interrupted:
                    interrupted = True
                    raise error
                return wait(timeout=timeout)
            monkeypatch.setattr(child, 'wait', interrupt_once)
        return child

    monkeypatch.setattr(subprocess, 'Popen', spawn_fixture)
    monkeypatch.setattr(browser, '_find_agent_browser', lambda: 'fixture-browser')
    monkeypatch.setattr(browser, '_is_local_mode', lambda: True)
    monkeypatch.setattr(browser, '_chromium_installed', lambda: True)
    monkeypatch.setattr(browser, '_is_camofox_mode', lambda: False)
    monkeypatch.setattr(browser, '_get_browser_engine', lambda: 'chrome')
    monkeypatch.setattr(browser, '_socket_safe_tmpdir', lambda: str(tmp_path))
    monkeypatch.setattr(browser, '_write_owner_pid', lambda *args: None)
    monkeypatch.setattr('tools.interrupt.is_interrupted', lambda: False)
    result = None
    raised = None
    try:
        try:
            if route == 'primary':
                result = browser._run_browser_command(
                    'fixture', 'snapshot', timeout=1,
                    _session_info={'session_name': 'fixture'},
                )
            else:
                monkeypatch.setattr(browser, '_run_browser_command', lambda *args, **kwargs: {
                    'success': True, 'data': {'result': 'https://fixture.invalid/'},
                })
                result = browser._run_chrome_fallback_command('fixture', 'snapshot', [], 1)
        except BaseException as exc:
            raised = exc
        assert children, 'The test must exercise a real child process'
        assert children[0][0].returncode is not None, 'Browser command child was not reaped'
        if failure == 'interrupt' or (route == 'chrome_fallback' and failure == 'unexpected_timeout'):
            assert raised is error
        else:
            assert raised is None
            assert result['success'] is False
    finally:
        # Negative controls must not leave their intentionally sleeping children behind.
        for child, wait in children:
            if child.poll() is None:
                child.kill()
            wait(timeout=5)


@pytest.mark.parametrize('route', ['primary', 'chrome_fallback'])
@pytest.mark.parametrize('failure', ['open_stderr', 'spawn'])
def test_failed_launch_closes_every_allocated_output(monkeypatch, tmp_path, route, failure):
    import os
    from unittest.mock import Mock

    opened = []
    original_open = os.open
    def open_output(path, flags, mode=0o777, **kwargs):
        if failure == 'open_stderr' and '/_stderr_' in str(path):
            raise OSError('stderr allocation failed')
        fd = original_open(path, flags, mode, **kwargs)
        if '/_stdout_' in str(path) or '/_stderr_' in str(path):
            stat = os.fstat(fd)
            opened.append((fd, stat.st_dev, stat.st_ino))
        return fd

    monkeypatch.setattr(os, 'open', open_output)
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=OSError('spawn failed')))
    monkeypatch.setattr(browser, '_find_agent_browser', lambda: 'fixture-browser')
    monkeypatch.setattr(browser, '_is_local_mode', lambda: True)
    monkeypatch.setattr(browser, '_chromium_installed', lambda: True)
    monkeypatch.setattr(browser, '_is_camofox_mode', lambda: False)
    monkeypatch.setattr(browser, '_get_browser_engine', lambda: 'chrome')
    monkeypatch.setattr(browser, '_socket_safe_tmpdir', lambda: str(tmp_path))
    monkeypatch.setattr(browser, '_write_owner_pid', lambda *args: None)
    monkeypatch.setattr('tools.interrupt.is_interrupted', lambda: False)
    try:
        try:
            if route == 'primary':
                browser._run_browser_command('fixture', 'snapshot', timeout=1,
                                             _session_info={'session_name': 'fixture'})
            else:
                monkeypatch.setattr(browser, '_run_browser_command', lambda *args, **kwargs: {
                    'success': True, 'data': {'result': 'https://fixture.invalid/'},
                })
                browser._run_chrome_fallback_command('fixture', 'snapshot', [], 1)
        except OSError:
            pass
        assert opened
        leaked = []
        for fd, device, inode in opened:
            try:
                stat = os.fstat(fd)
            except OSError:
                continue
            if (stat.st_dev, stat.st_ino) == (device, inode):
                leaked.append(fd)
        assert not leaked, f"Output descriptors leaked: {leaked}"
    finally:
        # Only release this test's files; a reused descriptor belongs elsewhere.
        for fd, device, inode in set(opened):
            try:
                stat = os.fstat(fd)
                if (stat.st_dev, stat.st_ino) == (device, inode):
                    os.close(fd)
            except OSError:
                pass
