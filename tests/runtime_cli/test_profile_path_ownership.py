"""Profile selection is shared admission, not profile administration."""
import builtins

import pytest

from superforecasting_agent import profile_paths


@pytest.mark.parametrize('name', ['../escape', '/absolute', 'forecast', 'bad/name', '', 'a' * 65])
def test_direct_profile_paths_reject_invalid_names(name):
    with pytest.raises(ValueError):
        profile_paths.get_profile_dir(name)


def test_strict_validation_rejects_trailing_newline():
    with pytest.raises(ValueError):
        profile_paths.validate_profile_name('analyst\n')


def test_cron_profile_admission_uses_shared_paths_without_administration(tmp_path, monkeypatch):
    from cron.jobs import _normalize_profile
    monkeypatch.setattr(profile_paths, 'get_default_agent_root', lambda: tmp_path)
    (tmp_path / 'profiles' / 'analyst').mkdir(parents=True)
    original = builtins.__import__
    imports = []
    def guarded(name, *args, **kwargs):
        if name == 'superforecasting_agent.runtime.profiles':
            imports.append(name)
            raise AssertionError('cron profile selection imported administration')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guarded)
    assert _normalize_profile(' Analyst ') == 'analyst'
    assert _normalize_profile('DEFAULT') == 'default'
    assert _normalize_profile(None) is None
    assert profile_paths.resolve_profile_env('Analyst') == str(tmp_path / 'profiles' / 'analyst')
    with pytest.raises(FileNotFoundError):
        _normalize_profile('missing')
    assert imports == []
