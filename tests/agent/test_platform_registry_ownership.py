"""Platform metadata must be usable without initializing messaging transports."""
import subprocess
import sys


def test_compatibility_registry_is_the_same_singleton():
    from superforecasting_agent import platform_registry as owner
    from gateway import platform_registry as legacy
    assert legacy is owner
    assert legacy.platform_registry is owner.platform_registry
    entry = owner.PlatformEntry('ownership-fixture', 'Fixture', lambda cfg: cfg, lambda: True)
    try:
        owner.platform_registry.register(entry)
        assert legacy.platform_registry.get(entry.name) is entry
        assert legacy.platform_registry.unregister(entry.name)
        assert not owner.platform_registry.is_registered(entry.name)
    finally:
        owner.platform_registry.unregister(entry.name)


def test_reading_platform_metadata_never_initializes_gateway_or_factory():
    code = '''
import builtins
original = builtins.__import__
def guarded(name, *args, **kwargs):
    if name == 'gateway' or name.startswith(('gateway.', 'tui_gateway')) or name == 'cli':
        raise AssertionError('platform metadata imported messaging: ' + name)
    return original(name, *args, **kwargs)
builtins.__import__ = guarded
from superforecasting_agent.platform_registry import PlatformEntry, PlatformRegistry
registry = PlatformRegistry()
def forbidden(*args):
    raise AssertionError('metadata lookup initialized an adapter or checked dependencies')
entry = PlatformEntry('fixture', 'Fixture', forbidden, forbidden, platform_hint='Plain text')
registry.register(entry)
assert registry.get('fixture').platform_hint == 'Plain text'
assert registry.all_entries() == [entry]
assert registry.plugin_entries() == [entry]
assert registry.unregister('fixture')
assert not registry.is_registered('fixture')
'''
    result = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stdout + result.stderr
