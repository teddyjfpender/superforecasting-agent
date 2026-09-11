"""Liveness probes never signal Windows processes and release native handles."""
import ctypes
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from superforecasting_agent import processes


@pytest.mark.parametrize('result, alive', [(0x102, True), (0, False), (0xFFFFFFFF, False)])
def test_windows_fallback_preserves_full_width_handle_and_closes(monkeypatch, result, alive):
    monkeypatch.setitem(sys.modules, 'psutil', None)
    monkeypatch.setattr(processes, '_IS_WINDOWS', True)
    handle = 0x123456789
    seen = []
    kernel = SimpleNamespace(
        OpenProcess=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_uint)(lambda *args: handle),
        WaitForSingleObject=ctypes.CFUNCTYPE(ctypes.c_uint, ctypes.c_void_p, ctypes.c_uint)(lambda h, timeout: seen.append(('wait', h)) or result),
        CloseHandle=ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p)(lambda h: seen.append(('close', h)) or 1),
        GetLastError=ctypes.CFUNCTYPE(ctypes.c_uint)(lambda: 0),
    )
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=kernel), raising=False)
    kill = Mock(side_effect=AssertionError('Windows liveness must not signal'))
    monkeypatch.setattr(processes.os, 'kill', kill)
    assert processes.pid_exists(123) is alive
    assert seen == [('wait', handle), ('close', handle)]
    assert kernel.WaitForSingleObject.argtypes == [ctypes.c_void_p, ctypes.c_uint]
    assert kernel.CloseHandle.argtypes == [ctypes.c_void_p]
    kill.assert_not_called()


@pytest.mark.parametrize('error, alive', [(87, False), (5, True)])
def test_windows_missing_or_inaccessible_process_has_no_handle_to_close(monkeypatch, error, alive):
    monkeypatch.setitem(sys.modules, 'psutil', None)
    monkeypatch.setattr(processes, '_IS_WINDOWS', True)
    kernel = SimpleNamespace(OpenProcess=Mock(return_value=None), WaitForSingleObject=Mock(),
                             CloseHandle=Mock(), GetLastError=Mock(return_value=error))
    monkeypatch.setattr(ctypes, 'windll', SimpleNamespace(kernel32=kernel), raising=False)
    assert processes.pid_exists(123) is alive
    kernel.CloseHandle.assert_not_called()
    kernel.WaitForSingleObject.assert_not_called()
