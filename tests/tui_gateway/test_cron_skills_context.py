"""Cron/skills registrations retain service and host ownership through draining."""

import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway.cron_skills_rpc import CronSkillsContext, register_handlers


def install(context):
    handlers = {}
    def register(name):
        def decorate(handler):
            handlers[name] = handler
            return handler
        return decorate
    register_handlers(context, method=register)
    return handlers


def context_for(name):
    host = RuntimeHost()
    context = CronSkillsContext(
        host=lambda: host,
        cron=lambda **args: json.dumps({'owner': name, **args}),
        available_skills=lambda: {'general': [name]},
        search=lambda query: [{'name': name, 'description': query}],
        install=lambda query: query == name,
        browse=lambda page, size: {'owner': name, 'page': page, 'page_size': size},
        inspect=lambda query: {'name': name, 'query': query},
        reload=lambda: {'added': [{'name': name}], 'removed': [], 'total': 1},
        ok=lambda rid, result: {'id': rid, 'result': result},
        error=lambda rid, code, message: {'id': rid, 'error': {'code': code, 'message': message}},
    )
    return host, context


def test_registrations_keep_services_responses_and_shutdown_independent():
    first, a = context_for('one')
    second, b = context_for('two')
    handlers_a, handlers_b = install(a), install(b)
    for name, handlers in [('one', handlers_a), ('two', handlers_b)]:
        assert handlers['cron.manage'](1, {})['result'] == {'owner': name, 'action': 'list'}
        assert handlers['cron.manage'](2, {'action': 'add', 'name': 'job', 'schedule': 'daily', 'prompt': 'review'})['result'] == {
            'owner': name, 'action': 'create', 'name': 'job', 'schedule': 'daily', 'prompt': 'review'}
        assert handlers['skills.manage'](3, {})['result'] == {'skills': {'general': [name]}}
        assert handlers['skills.manage'](4, {'action': 'install', 'query': name})['result']['installed']
        assert handlers['skills.manage'](5, {'action': 'search', 'query': 'needle'})['result']['results'][0]['name'] == name
        assert handlers['skills.manage'](6, {'action': 'browse', 'query': '3'})['result'] == {'owner': name, 'page': 3, 'page_size': 20}
        assert handlers['skills.manage'](7, {'action': 'inspect', 'query': 'item'})['result']['info']['name'] == name
        assert name in handlers['skills.reload'](8, {})['result']['output']
    first.workers.stop()
    for handler in handlers_a.values():
        assert handler(9, {})['error']['code'] == 5030
    assert handlers_b['cron.manage'](10, {})['result']['owner'] == 'two'
    second.workers.stop()
    assert first.workers.drain(0) and second.workers.drain(0)


@pytest.mark.parametrize('method,field,code', [
    ('cron.manage', 'cron', 5023), ('skills.manage', 'available_skills', 5024),
    ('skills.reload', 'reload', 5025),
])
def test_service_failures_preserve_domain_codes(method, field, code):
    host, context = context_for('errors')
    def fail(*args, **kwargs):
        raise OSError('controlled failure')
    handlers = install(replace(context, **{field: fail}))
    assert handlers[method](1, {})['error'] == {'code': code, 'message': 'controlled failure'}
    assert handlers['cron.manage'](2, {'action': 'unknown'})['error']['code'] == 4016
    assert handlers['skills.manage'](3, {'action': 'unknown'})['error']['code'] == 4017
    host.workers.stop()
    assert host.workers.drain(0)


def test_admitted_call_stays_owned_until_service_returns():
    host, context = context_for('draining')
    entered, release = threading.Event(), threading.Event()
    def search(query):
        entered.set()
        assert release.wait(5)
        return [{'name': query, 'description': 'completed'}]
    handlers = install(replace(context, search=search))
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending = pool.submit(handlers['skills.manage'], 1, {'action': 'search', 'query': 'owned'})
        try:
            assert entered.wait(3)
            host.workers.stop()
            assert not host.workers.drain(0)
            assert handlers['skills.reload'](2, {})['error']['code'] == 5030
            release.set()
            assert pending.result(3)['result']['results'][0]['name'] == 'owned'
            assert host.workers.drain(0)
        finally:
            release.set()


def test_singleton_install_uses_supported_quiet_console(monkeypatch, capsys):
    from rich.console import Console
    from superforecasting_agent.runtime import skills_hub
    from tui_gateway.cron_skills_rpc import _install

    def install_skill(query, *, skip_confirm, console):
        assert query == 'owner/skill' and skip_confirm
        assert isinstance(console, Console)
        console.print('installer progress must not corrupt JSON-RPC stdout')
        return True

    monkeypatch.setattr(skills_hub, 'do_install', install_skill)
    assert _install('owner/skill')
    assert capsys.readouterr().out == ''
