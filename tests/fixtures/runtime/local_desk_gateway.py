"""Test-only provider seam; all gateway, transport and journal code is real."""

def main():
    import json
    import os
    from pathlib import Path
    import threading
    import uuid
    from urllib.request import urlopen

    import socket
    _connect = socket.socket.connect
    def local_connect(sock, address):
        if isinstance(address, tuple) and address[0] not in ('127.0.0.1', '::1', 'localhost'):
            raise OSError('external network disabled in local desk fixture')
        return _connect(sock, address)
    socket.socket.connect = local_connect

    from tui_gateway import server
    if os.environ.get('FORECAST_TEST_FORBID_CLASSIC_WORKER') == '1':
        def forbidden_worker(*args, **kwargs):
            raise AssertionError('classic worker construction forbidden in native command test')
        server._SlashWorker = forbidden_worker
    server.start_build_check = lambda: None
    if os.environ.get('FORECAST_TEST_STORE_FAILURE') == '1':
        server._get_db = lambda: None
        server._host.store.last_error = 'fixture store unavailable'
    server._methods['setup.status'] = lambda rid, params: server._ok(rid, {'provider_configured': True})


    home = Path(os.environ['SUPERFORECASTING_AGENT_HOME'])

    if os.environ.get('FORECAST_TEST_DELEGATION_AUDIT') == '1':
        from superforecasting_agent.hosting import delegations
        original_pause = delegations.set_spawn_paused
        def audited_pause(paused, *, session_key=None):
            result = original_pause(paused, session_key=session_key)
            with delegations._spawn_pause_lock:
                paused_sessions = sorted(delegations._spawn_paused_sessions)
            with (home / 'delegation-pause.jsonl').open('a', encoding='utf-8') as stream:
                stream.write(json.dumps({'owner': session_key, 'paused': result, 'paused_sessions': paused_sessions}) + '\n')
            return result
        delegations.set_spawn_paused = audited_pause

    if os.environ.get('FORECAST_TEST_HANDOFF') == '1':
        from contextlib import closing
        from types import SimpleNamespace
        import gateway.config as gateway_config
        from superforecasting_agent.storage.session import SessionDB
        gateway_config.load_gateway_config = lambda: SimpleNamespace(
            platforms={gateway_config.Platform.TELEGRAM: SimpleNamespace(enabled=True)},
            get_home_channel=lambda platform: SimpleNamespace(chat_id='local-fixture'),
        )
        original_request = SessionDB.request_handoff
        def request_handoff(db, key, platform, *, attempt_id=None):
            result = original_request(db, key, platform, attempt_id=attempt_id)
            if result:
                def transfer():
                    with closing(SessionDB(db_path=db.db_path)) as remote:
                        if remote.claim_handoff(key, attempt_id=attempt_id):
                            remote.complete_handoff(key, attempt_id=attempt_id)
                threading.Thread(target=transfer, daemon=True).start()
            return result
        SessionDB.request_handoff = request_handoff

    def lifetime(event, identity):
        with (home / 'agent-lifetime.jsonl').open('a', encoding='utf-8') as stream:
            stream.write(json.dumps({'event': event, 'agent': identity}) + '\n')

    class LocalProvider:
        model = 'local-fixture'
        provider = 'fixture'

        def __init__(self, key):
            self.session_id = key
            self.identity = uuid.uuid4().hex
            lifetime('created', self.identity)
            self.stopped = threading.Event()
            if not server._get_db().get_session(key):
                server._get_db().create_session(key, source='tui', model=self.model)

        def interrupt(self):
            self.stopped.set()

        def close(self):
            lifetime('closed', self.identity)
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


    def make_agent(sid, key, session_id=None):
        failure = home / 'fail-next-agent-build'
        if failure.exists():
            failure.unlink()
            raise RuntimeError('fixture rebuild unavailable')
        return LocalProvider(session_id or key)

    server._make_agent = make_agent
    Path(os.environ['FORECAST_TEST_GATEWAY_PID']).write_text(str(os.getpid()))
    from tui_gateway.entry import main as gateway_main
    gateway_main()


if __name__ == "__main__":
    main()
