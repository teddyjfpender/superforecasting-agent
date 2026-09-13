"""Startup loading preserves plugin keys without loading CLI configuration."""

import subprocess
import sys


def test_loading_plugin_credentials_does_not_import_runtime(tmp_path):
    home = tmp_path / 'profile'
    home.mkdir()
    (home / '.env').write_text('PLUGIN_TOKEN=firstOPENAI_API_KEY=second\n', encoding='utf-8')
    plugin = tmp_path / 'plugins' / 'platforms' / 'example'
    plugin.mkdir(parents=True)
    (plugin / 'plugin.yaml').write_text('requires_env:\n  - PLUGIN_TOKEN\n', encoding='utf-8')
    (plugin / '__init__.py').write_text('raise AssertionError("plugin imported")\n', encoding='utf-8')
    result = subprocess.run([sys.executable, '-c', '''
import os, sys
from pathlib import Path
from superforecasting_agent import paths, startup_environment
root = Path(sys.argv[1])
paths.get_install_root = lambda: root
loaded = startup_environment.load_forecast_dotenv(hermes_home=root / 'profile')
assert loaded == [root / 'profile' / '.env']
assert os.environ['PLUGIN_TOKEN'] == 'first'
assert os.environ['OPENAI_API_KEY'] == 'second'
assert not any(n == 'superforecasting_agent.runtime' or n.startswith('superforecasting_agent.runtime.') for n in sys.modules)
''', str(tmp_path)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr


def test_legacy_import_shares_the_same_mutable_owner():
    from superforecasting_agent import startup_environment
    from superforecasting_agent.runtime import env_loader
    assert env_loader is startup_environment
    assert env_loader._SECRET_SOURCES is startup_environment._SECRET_SOURCES
    assert env_loader._WARNED_KEYS is startup_environment._WARNED_KEYS


def test_startup_repair_preserves_concurrent_credential_write(tmp_path, monkeypatch):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    from superforecasting_agent import startup_environment
    from superforecasting_agent.configuration import env_lines
    from superforecasting_agent.runtime import config
    path = tmp_path / '.env'
    path.write_text('OPENAI_API_KEY=firstANTHROPIC_API_KEY=second\n', encoding='utf-8')
    monkeypatch.setattr(config, 'get_env_path', lambda: path)
    monkeypatch.setattr(config, 'ensure_hermes_home', lambda: None)
    monkeypatch.setattr(config, 'is_managed', lambda: False)
    monkeypatch.delenv('EXA_API_KEY', raising=False)
    original = env_lines.sanitize_env_lines
    repair_read, release = threading.Event(), threading.Event()
    writer_started, writer_done = threading.Event(), threading.Event()
    def paused_parse(lines, known_keys):
        if not repair_read.is_set():
            repair_read.set()
            assert release.wait(5)
        return original(lines, known_keys)
    monkeypatch.setattr(env_lines, 'sanitize_env_lines', paused_parse)
    def write_key():
        writer_started.set()
        config.save_env_value('EXA_API_KEY', 'third')
        writer_done.set()
    with ThreadPoolExecutor(max_workers=2) as pool:
        repair = pool.submit(startup_environment._sanitize_env_file_if_needed, path)
        try:
            assert repair_read.wait(5)
            writer = pool.submit(write_key)
            assert writer_started.wait(5)
            writer_done.wait(0.2)
        finally:
            release.set()
        repair.result(timeout=5)
        writer.result(timeout=5)
    text = path.read_text(encoding='utf-8')
    assert 'OPENAI_API_KEY=first\n' in text
    assert 'ANTHROPIC_API_KEY=second\n' in text
    assert 'EXA_API_KEY=third' in text
