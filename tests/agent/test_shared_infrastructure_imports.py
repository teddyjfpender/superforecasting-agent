"""Local media and process checks must work without messaging dependencies."""
import os
import subprocess
import sys


def test_media_tracks_active_profile_without_gateway_imports(tmp_path):
    code = '''
import builtins
import os
from pathlib import Path
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'gateway' or name.startswith(('gateway.', 'tui_gateway')) or name == 'cli':
        raise AssertionError('shared infrastructure imported messaging: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from superforecasting_agent.processes import pid_exists
from superforecasting_agent.storage.media import cache_image_from_bytes
assert pid_exists(os.getpid())
base = Path(os.environ['MEDIA_OWNER_TEST_ROOT'])
data = b'\\x89PNG\\r\\n\\x1a\\nfixture'
for profile in ('one', 'two'):
    os.environ['SUPERFORECASTING_AGENT_HOME'] = str(base / profile)
    image = Path(cache_image_from_bytes(data, '.png'))
    assert image.parent == base / profile / 'cache' / 'images'
    assert image.read_bytes() == data
try:
    cache_image_from_bytes(b'<html>not an image</html>', '.png')
except ValueError:
    pass
else:
    raise AssertionError('invalid media was cached')
'''
    result = subprocess.run([sys.executable, '-c', code], env={**os.environ, 'MEDIA_OWNER_TEST_ROOT': str(tmp_path)}, capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
