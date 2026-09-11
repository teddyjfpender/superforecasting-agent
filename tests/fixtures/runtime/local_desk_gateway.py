"""Test-only provider seam; all gateway, transport and journal code is real."""
import json
import os
from pathlib import Path
import threading
from urllib.request import urlopen

import socket
_connect = socket.socket.connect
def local_connect(sock, address):
    if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
        raise OSError('external network disabled in local desk fixture')
    return _connect(sock, address)
socket.socket.connect = local_connect

from tui_gateway import server
server.start_build_check = lambda: None
if os.environ.get('FORECAST_TEST_STORE_FAILURE') == '1':
    server._get_db = lambda: None
    server._db_error = 'fixture store unavailable'
server._methods['setup.status'] = lambda rid, params: server._ok(rid, {'provider_configured': True})


class LocalProvider:
    model = 'local-fixture'
    provider = 'fixture'

    def __init__(self, key):
        self.session_id = key
        self.stopped = threading.Event()
        if not server._get_db().get_session(key):
            server._get_db().create_session(key, source='tui', model=self.model)

    def interrupt(self):
        self.stopped.set()

    def close(self):
        self.stopped.set()

    def run_conversation(self, message, *, stream_callback, conversation_history):
        from urllib.parse import urlencode
        self.stopped.clear()
        text = ''
        with urlopen(os.environ['FORECAST_TEST_PROVIDER_URL'] + '?' + urlencode({'prompt': message}), timeout=5) as response:
            for line in response:
                if self.stopped.is_set():
                    return {'final_response': text, 'interrupted': True, 'messages': conversation_history}
                item = json.loads(line)
                if item.get('error'):
                    raise RuntimeError(item['error'])
                if item.get('delta'):
                    text += item['delta']
                    stream_callback(item['delta'])
                if item.get('done'):
                    return {'final_response': text, 'messages': [*conversation_history, {'role': 'user', 'content': message}, {'role': 'assistant', 'content': text}]}
        raise RuntimeError('local provider stream ended without completion')


server._make_agent = lambda sid, key, session_id=None: LocalProvider(session_id or key)
Path(os.environ['FORECAST_TEST_GATEWAY_PID']).write_text(str(os.getpid()))
from tui_gateway.entry import main
main()
