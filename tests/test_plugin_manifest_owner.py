"""Plugin declarations are validated before registration can consume them."""

import pytest

from superforecasting_agent.configuration.plugin_manifest import PluginManifest, parse_manifest


def parse(data):
    return parse_manifest(data, directory_name="example", path="/plugins/example", source="user")


@pytest.mark.parametrize("data", [False, [], "name", {"name": []}, {"name": " "}, {"author": 1}, {"requires_env": "TOKEN"}, {"requires_env": [{}]}, {"provides_tools": [False]}, {"provides_hooks": None}])
def test_invalid_declarations_are_rejected(data):
    with pytest.raises(ValueError):
        parse(data)


def test_defaults_and_metadata_declarations():
    manifest = parse({"version": 2, "requires_env": ["TOKEN", {"name": "OTHER", "password": True}], "kind": " BACKEND "})
    assert manifest.name == manifest.key == "example"
    assert manifest.version == "2"
    assert manifest.kind == "backend"
    assert manifest.requires_env[1] == {"name": "OTHER", "password": True}
    assert parse({"kind": "future-kind"}).kind == "standalone"


def test_compatibility_type_identity():
    from superforecasting_agent.runtime.plugins import PluginManifest as LegacyManifest

    assert LegacyManifest is PluginManifest


def test_invalid_manifest_is_not_admitted_by_manager(tmp_path):
    from superforecasting_agent.runtime.plugins import PluginManager

    manifest_path = tmp_path / "plugin.yaml"
    manifest_path.write_text("name: example\nprovides_tools: wrong-type\n", encoding="utf-8")
    (tmp_path / "__init__.py").write_text("raise AssertionError('must not execute')", encoding="utf-8")
    assert PluginManager()._parse_manifest(manifest_path, tmp_path, "user", "") is None


def test_shipped_manifests_satisfy_declaration_contract():
    from pathlib import Path
    import yaml

    paths = sorted((Path(__file__).resolve().parents[1] / "plugins").rglob("plugin.yaml"))
    assert paths
    for path in paths:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        parse_manifest(data, directory_name=path.parent.name, path=str(path.parent), source="bundled")


@pytest.mark.parametrize("source_text, explicit_kind, expected", [
    ("raise AssertionError('never execute')\n# MemoryProvider", None, "exclusive"),
    ("# register_provider ProviderProfile", None, "model-provider"),
    ("# MemoryProvider", "standalone", "standalone"),
    (" " * 8192 + "MemoryProvider", None, "standalone"),
])
def test_reader_routes_legacy_providers_without_execution(tmp_path, source_text, explicit_kind, expected):
    import yaml
    from superforecasting_agent.storage.plugin_manifests import read_plugin_manifest

    data = {"name": "example"}
    if explicit_kind is not None:
        data["kind"] = explicit_kind
    manifest_path = tmp_path / "plugin.yaml"
    manifest_path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (tmp_path / "__init__.py").write_text(source_text, encoding="utf-8")
    manifest = read_plugin_manifest(manifest_path, tmp_path, "user", "memory")
    assert manifest.kind == expected
    assert manifest.key == f"memory/{tmp_path.name}"


def test_reader_import_does_not_initialize_runtime():
    import subprocess
    import sys

    subprocess.run([sys.executable, "-c", "from superforecasting_agent.storage.plugin_manifests import read_plugin_manifest; import sys; assert not any(k.startswith(('superforecasting_agent.runtime', 'agent.', 'tui_gateway')) for k in sys.modules)"], check=True)
