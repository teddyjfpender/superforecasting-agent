"""Explicit service credentials for live integration runs; unit tests stay hermetic."""
import os
from pathlib import Path

import pytest

SERVICE_KEYS = {
    'daytona': ('DAYTONA_API_KEY',),
    'modal': ('MODAL_TOKEN_ID', 'MODAL_TOKEN_SECRET'),
}
SERVICE_FILES = {'test_daytona_terminal.py': 'daytona', 'test_modal_terminal.py': 'modal'}
_CREDENTIALS = pytest.StashKey[dict]()


def pytest_addoption(parser):
    parser.addoption('--live-service', action='append', choices=tuple(SERVICE_KEYS), default=[],
                     help='Explicitly enable credentialed Daytona/Modal integration tests (may create billed sandboxes)')


def pytest_configure(config):
    # Capture only explicitly selected service keys, never the whole environment.
    config.stash[_CREDENTIALS] = {
        service: {key: os.environ[key] for key in SERVICE_KEYS[service] if os.environ.get(key)}
        for service in config.getoption('--live-service')
    }


@pytest.fixture(autouse=True)
def _selected_live_service_credentials(request, _hermetic_environment, monkeypatch):
    service = SERVICE_FILES.get(Path(str(request.node.path)).name)
    if service is None:
        return
    credentials = request.config.stash.get(_CREDENTIALS, {}).get(service)
    if credentials is None:
        pytest.skip('live service disabled; explicitly pass --live-service=' + service)
    if set(credentials) != set(SERVICE_KEYS[service]):
        pytest.skip('required credentials are not configured for ' + service)
    for key, value in credentials.items():
        monkeypatch.setenv(key, value)
