import yaml
import pytest
from superforecasting_agent.runtime.model_configuration import model_section, persist_model_selection


def test_scalar_alias_and_root_fallback_have_one_interpretation():
    assert model_section({'model': ' example ', 'provider': 'custom'}) == {'default': 'example', 'provider': 'custom'}
    assert model_section({'model': {'model': 'explicit'}, 'base_url': 'https://example.org'})['default'] == 'explicit'
    with pytest.raises(ValueError, match='must be a string'):
        model_section({'model': {'provider': 123}})


def test_persist_switch_preserves_comments_and_references_but_not_old_route(tmp_path):
    p = tmp_path/'config.yaml'
    p.write_text('# desk settings\nmodel: old-model\nprovider: custom\nbase_url: https://old.invalid\nterminal:\n  cwd: ${WORKSPACE}\n')
    assert persist_model_selection(p, model='new-model', provider='gemini', base_url='https://new.invalid', api_mode='chat_completions')
    cfg = yaml.safe_load(p.read_text())
    assert cfg['model']['default'] == 'new-model' and cfg['model']['base_url'] == 'https://new.invalid'
    assert 'provider' not in cfg and 'base_url' not in cfg
    assert cfg['terminal']['cwd'] == '${WORKSPACE}' and '# desk settings' in p.read_text()
    cfg['model']['api_key'] = '${OLD_KEY}'
    p.write_text(yaml.safe_dump(cfg))
    persist_model_selection(p, model='other', provider='other-provider')
    assert 'api_key' not in yaml.safe_load(p.read_text())['model']
    assert model_section(yaml.safe_load(p.read_text()))['base_url'] == ''


def test_profile_and_diagnostics_share_legacy_provider_precedence(tmp_path):
    from superforecasting_agent.runtime.profiles import _read_config_model
    from superforecasting_agent.runtime.dump import _get_model_and_provider
    config = {'model': ' example ', 'provider': 'custom'}
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(config))
    assert _read_config_model(tmp_path) == ('example', 'custom')
    assert _get_model_and_provider(config) == ('example', 'custom')
    config['model'] = {'default': 'example', 'provider': 'auto'}
    (tmp_path / 'config.yaml').write_text(yaml.safe_dump(config))
    assert _read_config_model(tmp_path) == ('example', 'auto')
    assert _get_model_and_provider(config) == ('example', 'auto')
