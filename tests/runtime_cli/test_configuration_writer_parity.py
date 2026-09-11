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
