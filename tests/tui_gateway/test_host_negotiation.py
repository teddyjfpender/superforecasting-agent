"""Compatibility admission uses registered behavior, without starting sessions."""
import pytest

from protocol.version import PROTOCOL_VERSION
from tui_gateway import host_rpc, server


def negotiate(params):
    return server.handle_request({'jsonrpc': '2.0', 'id': 'host-test',
                                  'method': 'host.negotiate', 'params': params})


def test_host_negotiates_real_operations_and_detects_missing_handler(monkeypatch):
    request = {'protocol_version': PROTOCOL_VERSION, 'required_capabilities': ['forecast.operation', 'session.resume']}
    result = negotiate(request)['result']
    assert result == host_rpc.descriptor(server)
    monkeypatch.delitem(server._methods, 'forecast.operation')
    response = negotiate(request)
    assert response['error']['code'] == 4004
    assert 'forecast.operation' in response['error']['message']
    assert 'forecast.operation' not in host_rpc.descriptor(server)['capabilities']


@pytest.mark.parametrize('params,code', [
    ({'protocol_version': PROTOCOL_VERSION + 1}, 4004),
    ({'protocol_version': True}, -32602),
    ({'protocol_version': '1'}, -32602),
    ({'protocol_version': 1, 'required_capabilities': 'session.create'}, -32602),
    ({'protocol_version': 1, 'unknown': True}, -32602),
])
def test_invalid_or_incompatible_request_never_initializes_session(params, code, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('negotiation started a session')
    monkeypatch.setattr(server, '_make_agent', forbidden)
    monkeypatch.setattr(server, '_get_db', forbidden)
    assert negotiate(params)['error']['code'] == code
