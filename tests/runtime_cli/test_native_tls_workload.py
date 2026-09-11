"""Check experiment controls without treating this host as native crash evidence."""
import json
import time
from types import SimpleNamespace

import pytest
from scripts import investigate_native_tls as investigation


@pytest.mark.parametrize('mode', ['environment', 'environment-unset', 'explicit-ca-environment', 'explicit-ca-environment-unset'])
def test_mutation_cases_overlap_tls_and_preserve_explicit_ca_control(mode, monkeypatch, capsys):
    monkeypatch.setattr(investigation.os, 'environ', {})
    calls = []

    def context(*, cafile):
        calls.append(cafile)
        time.sleep(0.0001)
        return SimpleNamespace(cert_store_stats=lambda: {})

    monkeypatch.setattr(investigation.ssl, 'create_default_context', context)
    investigation.workload(mode, '/fixture/ca.pem')
    counts = json.loads(capsys.readouterr().out.removeprefix('WORKLOAD '))
    assert counts['contexts'] == 200
    assert counts['mutations'] > 0
    assert set(calls) == ({'/fixture/ca.pem'} if mode.startswith('explicit-ca-') else {None})
    remaining = len(investigation.os.environ)
    assert remaining == (10000 - counts['mutations'] if mode.endswith('-unset') else counts['mutations'])
