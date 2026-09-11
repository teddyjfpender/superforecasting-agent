"""Headless hosting uses the existing runtime wire contract without a dashboard."""
import builtins

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from superforecasting_agent.hosting.websocket import create_app


@pytest.mark.parametrize('url, headers, code', [
    ('/api/ws', {}, 4401),
    ('/api/ws?token=wrong', {}, 4401),
    ('/api/ws?token=fixture', {'origin': 'https://untrusted.example'}, 4403),
    ('/api/ws?token=fixture', {'authorization': 'Basic fixture'}, 4401),
    ('/api/ws?token=fixture', {'authorization': 'Bearer wrong'}, 4401),
])
def test_unauthorized_connection_never_enters_runtime(url, headers, code, monkeypatch):
    from tui_gateway import ws
    async def unexpected(*args):
        pytest.fail('unauthorized request reached the runtime')
    monkeypatch.setattr(ws, 'handle_ws', unexpected)
    with TestClient(create_app(token='fixture')) as client:
        with pytest.raises(WebSocketDisconnect) as exc:
            with client.websocket_connect(url, headers=headers):
                pytest.fail('unauthorized socket accepted')
        assert exc.value.code == code


@pytest.mark.parametrize('headers, origins', [({}, []), ({'authorization': 'Bearer fixture'}, []),
    ({'origin': 'https://desk.example'}, ['https://desk.example'])])
def test_authenticated_runtime_negotiates_and_reports_protocol_errors(headers, origins, monkeypatch):
    from tui_gateway import server
    monkeypatch.setattr(server, 'start_build_check', lambda: None)
    original = builtins.__import__
    forbidden = []
    def guarded(name, *args, **kwargs):
        if name == 'superforecasting_agent.runtime.web_server' or name.startswith('forecasting.dashboard'):
            forbidden.append(name)
            raise AssertionError('headless host imported dashboard')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    with TestClient(create_app(token='fixture', allowed_origins=origins)) as client:
        with client.websocket_connect('/api/ws?token=fixture', headers=headers) as ws:
            ready = ws.receive_json()['params']['payload']
            assert 'forecast.operation' in ready['capabilities']
            ws.send_json({'id': 1, 'method': 'host.negotiate', 'params': {
                'protocol_version': ready['protocol_version'], 'required_capabilities': ['forecast.operation']}})
            assert ws.receive_json()['result']['protocol_version'] == ready['protocol_version']
            ws.send_json({'id': 2, 'method': 'host.negotiate', 'params': {
                'protocol_version': ready['protocol_version'] + 1, 'required_capabilities': []}})
            assert ws.receive_json()['error']['code'] == 4004
            ws.send_text('{malformed')
            assert ws.receive_json()['error']['code'] == -32700
    assert forbidden == []


@pytest.mark.parametrize('token, origins', [('', []), (' ', []), ('fixture', ['*']), ('fixture', 'https://desk.example')])
def test_invalid_auth_configuration_fails_before_serving(token, origins):
    with pytest.raises(ValueError):
        create_app(token=token, allowed_origins=origins)
