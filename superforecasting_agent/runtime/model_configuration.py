"""Shared model-section interpretation and atomic CLI/gateway persistence."""
from pathlib import Path


from superforecasting_agent.configuration import model_section as model_section


def persist_model_selection(path, *, model, provider, base_url=None, api_mode=None):
    """Save a complete selection once; stale endpoint credentials never follow it."""
    from superforecasting_agent.runtime.config import is_managed, managed_error
    if is_managed():
        managed_error('save configuration')
        return False
    from superforecasting_agent.runtime.config import _CONFIG_LOCK
    from superforecasting_agent.storage.files import yaml_update_lock
    with _CONFIG_LOCK, yaml_update_lock(path):
        return _persist_model_selection(path, model=model, provider=provider, base_url=base_url, api_mode=api_mode)


def _persist_model_selection(path, *, model, provider, base_url, api_mode):
    from superforecasting_agent.storage.files import atomic_roundtrip_yaml_mutate
    path = Path(path)
    def update(cfg):
        current = model_section(cfg)
        selected = model_section({'model': {'default': model, 'provider': provider, 'base_url': base_url or '', 'api_mode': api_mode}})
        if not selected['default'] or not selected['provider']:
            raise ValueError('persisted model selection requires a model and provider')
        if current.get('provider') != selected['provider'] or (current.get('base_url') or '').rstrip('/') != (base_url or '').rstrip('/'):
            for key in ('api_key', 'api_mode', 'base_url'):
                current.pop(key, None)
        current.update({k: v for k, v in selected.items() if v is not None})
        current.pop('model', None)
        for key in ('provider', 'base_url', 'context_length'):
            cfg.pop(key, None)
        if isinstance(cfg.get('model'), dict):
            # Retain comments on unchanged nested fields.
            target = cfg['model']
            for key in list(target):
                if key not in current:
                    del target[key]
            target.update(current)
        else:
            cfg['model'] = current
    atomic_roundtrip_yaml_mutate(path, update)
    path.chmod(0o600)
    return True
