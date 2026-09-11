import pytest
import yaml
from superforecasting_agent.runtime import config
from superforecasting_agent.storage.files import atomic_roundtrip_yaml_update


def test_raw_snapshot_cannot_overwrite_concurrent_unrelated_setting(tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME',str(tmp_path))
    path=tmp_path/'config.yaml'; path.write_text('model: first\ndisplay:\n  skin: mono\n', encoding='utf-8')
    raw=config.read_raw_config()
    raw['model']='changed'
    atomic_roundtrip_yaml_update(path,'display.skin','forecast')
    with pytest.raises(ValueError, match='changed since'):
        config.save_config(raw)
    assert yaml.safe_load(path.read_text())=={'model':'first','display':{'skin':'forecast'}}


def test_dashboard_stale_form_and_yaml_edits_fail_without_losing_values(tmp_path, monkeypatch):
    from starlette.testclient import TestClient
    from superforecasting_agent.runtime import web_server
    monkeypatch.setenv('HERMES_HOME',str(tmp_path))
    path=tmp_path/'config.yaml'; path.write_text('model: first\n',encoding='utf-8')
    client=TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME]=web_server._SESSION_TOKEN
    form=client.get('/api/config').json()
    raw=client.get('/api/config/raw').json()
    atomic_roundtrip_yaml_update(path,'display.skin','forecast')
    form['model']='stale'
    assert client.put('/api/config',json={'config':form}).status_code==409
    assert client.put('/api/config/raw',json={'yaml_text':'model: stale','revision':raw['revision']}).status_code==409
    assert client.put('/api/config/raw',json={'yaml_text':'model: stale'}).status_code==428
    assert yaml.safe_load(path.read_text())['display']['skin']=='forecast'
    fresh=client.get('/api/config').json(); fresh['model']='new'
    result=client.put('/api/config',json={'config':fresh})
    assert result.status_code==200
    assert result.json()['revision'] != fresh['_revision']


def test_tui_stale_configuration_cannot_replace_a_new_setting(tmp_path, monkeypatch):
    from tui_gateway import server
    monkeypatch.setattr(server,'_hermes_home',tmp_path)
    monkeypatch.setattr(server,'_cfg_cache',None)
    path=tmp_path/'config.yaml'; path.write_text('model: first\n',encoding='utf-8')
    loaded=server._load_cfg(); loaded['model']='stale'
    atomic_roundtrip_yaml_update(path,'display.skin','forecast')
    with pytest.raises(ValueError, match='changed'):
        server._save_cfg(loaded)
    assert yaml.safe_load(path.read_text())['display']['skin']=='forecast'


def test_first_cli_setting_is_owned_by_the_profile(tmp_path, monkeypatch):
    import cli
    monkeypatch.setattr(cli,'_hermes_home',tmp_path)
    assert cli.save_config_value('display.skin','forecast')
    assert yaml.safe_load((tmp_path/'config.yaml').read_text())=={'display':{'skin':'forecast'}}


@pytest.mark.parametrize('value', ['on', 'off', 'yes', 'no', 'ON', 'OFF'])
@pytest.mark.parametrize('compound', [False, True])
def test_yaml_strings_keep_their_types_across_readers(tmp_path, value, compound):
    from superforecasting_agent.storage.files import atomic_roundtrip_yaml_mutate
    path = tmp_path / 'config.yaml'
    path.write_text('enabled: no\nactive: on\n# retain comment\n')
    if compound:
        atomic_roundtrip_yaml_mutate(path, lambda config: config.update(mode=value))
    else:
        atomic_roundtrip_yaml_update(path, 'mode', value)
    saved = yaml.safe_load(path.read_text())
    assert saved == {'enabled': False, 'active': True, 'mode': value}
    assert '# retain comment' in path.read_text()


def test_independent_runtime_loaders_share_snapshot_identity(tmp_path, monkeypatch):
    import importlib.util
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    original = config.load_config()
    spec = importlib.util.spec_from_file_location('isolated_config_loader', config.__file__)
    reloaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reloaded)
    changed = reloaded.load_config()
    changed['model'] = 'new-model'
    reloaded.save_config(changed)
    reloaded.reload_config_in_place(original)
    original['display']['skin'] = 'mono'
    config.save_config(original)
    assert config.load_config()['model'] == 'new-model'
    stale = config.load_config()
    atomic_roundtrip_yaml_update(tmp_path / 'config.yaml', 'display.skin', 'forecast')
    with pytest.raises(ValueError, match='changed since'):
        reloaded.save_config(stale)


@pytest.mark.parametrize('loader_name', ['read_raw_config', 'load_config', 'load_config_readonly', 'tui'])
def test_same_timestamp_and_size_edit_is_not_cached(tmp_path, monkeypatch, loader_name):
    import os
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    if loader_name == 'tui':
        from tui_gateway import server
        monkeypatch.setattr(server, '_hermes_home', tmp_path)
        monkeypatch.setattr(server, '_cfg_cache', None)
        load = server._load_cfg
        save = server._save_cfg
    else:
        load = getattr(config, loader_name)
        save = config.save_config
    path = tmp_path / 'config.yaml'
    path.write_text('display:\n  skin: mono\n')
    stamp = path.stat()
    assert load()['display']['skin'] == 'mono'
    path.write_text('display:\n  skin: ares\n')
    os.utime(path, ns=(stamp.st_atime_ns, stamp.st_mtime_ns))
    fresh = load()
    assert fresh['display']['skin'] == 'ares'
    if loader_name != 'load_config_readonly':
        fresh['test_setting'] = True
        save(fresh)
        assert yaml.safe_load(path.read_text())['display']['skin'] == 'ares'


def test_concurrent_credential_writers_preserve_both_updates(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    for key in ('TEST_ALPHA_API_KEY', 'TEST_BETA_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    first_at_replace = threading.Event()
    release_first = threading.Event()
    second_done = threading.Event()
    real_replace = config.atomic_replace

    def paused_replace(source, target):
        if not first_at_replace.is_set():
            first_at_replace.set()
            assert release_first.wait(5)
        return real_replace(source, target)

    def second_write():
        config.save_env_value('TEST_BETA_API_KEY', 'beta')
        second_done.set()

    monkeypatch.setattr(config, 'atomic_replace', paused_replace)
    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(config.save_env_value, 'TEST_ALPHA_API_KEY', 'alpha')
        try:
            assert first_at_replace.wait(5)
            second = pool.submit(second_write)
            # Before the lock fix, the second writer finishes and its change is
            # subsequently erased by the paused writer's older file snapshot.
            second_done.wait(0.2)
        finally:
            release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)
    text = (tmp_path / '.env').read_text()
    assert 'TEST_ALPHA_API_KEY=alpha' in text
    assert 'TEST_BETA_API_KEY=beta' in text
