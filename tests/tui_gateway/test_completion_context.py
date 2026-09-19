"""Completion hosts isolate roots, paste allocations and shutdown admission."""

from dataclasses import replace
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from superforecasting_agent.hosting.runtime import RuntimeHost
from tui_gateway.completion_rpc import CompletionContext, register_handlers


def completion_host(home, cwd):
    host = RuntimeHost()
    context = CompletionContext(
        host=lambda: host, home=lambda: home, cwd=lambda: str(cwd),
        list_repo_files=lambda root: [path.name for path in Path(root).iterdir()],
        fuzzy_basename_rank=lambda name, query: (0, 0) if query in name else None,
        normalize_path=lambda path: path, details=lambda text: None,
        skill_commands=lambda: {}, skill_bundles=lambda: {},
        ok=lambda rid, result: {'result': result},
        error=lambda rid, code, message: {'error': {'code': code, 'message': message}},
    )
    return host, context, install(context)


def install(context):
    handlers = {}

    def register(name):
        def decorate(handler):
            handlers[name] = handler
            return handler
        return decorate

    register_handlers(context, method=register, rpc_validated=register)
    return handlers


def test_two_hosts_keep_completions_pastes_and_shutdown_independent(tmp_path):
    roots = [tmp_path / 'one', tmp_path / 'two']
    for root in roots:
        root.mkdir()
        (root / (root.name + '.md')).touch()
    first, _, a = completion_host(roots[0], roots[0])
    second, _, b = completion_host(roots[1], roots[1])
    for handlers, root in zip((a, b), roots):
        for query in ('@file:', '@' + root.name):
            items = handlers['complete.path'](1, {'word': query})['result']['items']
            assert [item['text'] for item in items] == ['@file:' + root.name + '.md']
        result = handlers['paste.collapse'](2, {'text': root.name + '\nbody'})['result']
        path = Path(result['path'])
        assert path.parent == root / 'pastes'
        assert path.read_text() == root.name + '\nbody'
        assert result['lines'] == 2
        assert '#1:' in result['placeholder']
    first.workers.stop()
    assert first.workers.drain(0)
    assert a['paste.collapse'](3, {'text': 'blocked'})['error']['code'] == 5030
    assert '#2:' in b['paste.collapse'](4, {'text': 'alive'})['result']['placeholder']
    second.workers.stop()
    assert second.workers.drain(0)


def test_overlapping_hosts_in_one_profile_never_overwrite_pastes(tmp_path):
    first, _, a = completion_host(tmp_path, tmp_path)
    second, _, b = completion_host(tmp_path, tmp_path)
    def save(index):
        handler = (a, b)[index % 2]['paste.collapse']
        return handler(index, {'text': str(index)})['result']['path']
    with ThreadPoolExecutor(max_workers=4) as pool:
        paths = list(pool.map(save, range(20)))
    assert len(set(paths)) == 20
    assert [Path(path).read_text() for path in paths] == list(map(str, range(20)))
    assert a['paste.collapse'](21, {'text': ''})['error']['code'] == 4004
    for host in (first, second):
        host.workers.stop()
        assert host.workers.drain(0)


def test_completion_domain_errors_and_details_belong_to_registered_context(tmp_path):
    host, context, handlers = completion_host(tmp_path, tmp_path)
    special = install(replace(context, details=lambda text: [{'text': 'owned'}]))
    assert special['complete.slash'](1, {'text': '/details '})['result']['items'] == [{'text': 'owned'}]
    assert handlers['complete.slash'](2, {'text': 'plain'})['result']['items'] == []
    def fail(root):
        raise OSError('injected completion failure')
    failed = install(replace(context, list_repo_files=fail))
    assert failed['complete.path'](3, {'word': '@file'})['result']['items'] == []
    assert failed['complete.path'](4, {'word': '@needle'})['error']['code'] == 5021
    host.workers.stop()
    assert host.workers.drain(0)


def test_failed_paste_write_releases_only_its_partial_allocation(tmp_path, monkeypatch):
    import pytest
    from contextlib import contextmanager
    from types import SimpleNamespace
    from tui_gateway import completion_rpc

    host, _, handlers = completion_host(tmp_path, tmp_path)
    original = completion_rpc.tempfile.NamedTemporaryFile
    (tmp_path / 'pastes').mkdir()
    unrelated = tmp_path / 'pastes/existing.txt'
    unrelated.write_text('keep')

    @contextmanager
    def broken_file(**kwargs):
        with original(**kwargs) as stream:
            def fail(text):
                stream.write('partial')
                raise OSError('injected disk failure')
            yield SimpleNamespace(name=stream.name, write=fail)

    monkeypatch.setattr(completion_rpc.tempfile, 'NamedTemporaryFile', broken_file)
    with pytest.raises(OSError, match='injected disk failure'):
        handlers['paste.collapse'](1, {'text': 'draft'})
    assert list((tmp_path / 'pastes').iterdir()) == [unrelated]
    assert unrelated.read_text() == 'keep'
    host.workers.stop()
    assert host.workers.drain(0)
