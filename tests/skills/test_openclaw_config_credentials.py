"""Credential consent and report redaction also apply to service migration."""

import json

import pytest

from test_openclaw_migration import load_module


@pytest.mark.parametrize("migrate_secrets", [False, True])
@pytest.mark.parametrize("option,config,filename", [
    ("plugins-config", {"plugins": {"entries": {"demo": {"apiKey": "opaque-fixture", "enabled": True}}}}, "plugins-config.json"),
    ("gateway-config", {"gateway": {"auth": {"token": "opaque-fixture"}, "port": 9876}}, "gateway-config.json"),
    ("skills-config", {"skills": {"entries": {"demo": {"apiKey": "opaque-fixture"}}}}, "skills-registry-config.json"),
    ("deep-channels", {"channels": {"slack": {"accounts": {"default": {"appToken": "opaque-fixture"}}}}}, "channels-deep-config.json"),
])
def test_configuration_archives_redact_credentials(tmp_path, migrate_secrets, option, config, filename):
    mod = load_module()
    source = tmp_path / "source"
    source.mkdir()
    (source / "openclaw.json").write_text(json.dumps(config))
    output = tmp_path / "report"
    mod.Migrator(source_root=source, target_root=tmp_path / "target", execute=True,
                 workspace_target=None, overwrite=False, migrate_secrets=migrate_secrets,
                 output_dir=output, selected_options={option}).migrate()
    archive = output / "archive" / filename
    actual = json.loads(archive.read_text())
    assert "opaque-fixture" not in archive.read_text()
    assert "[redacted]" in archive.read_text()
    assert actual
    if option == "gateway-config":
        assert actual["port"] == 9876
    if option == "plugins-config":
        assert actual["entries"]["demo"]["enabled"] is True
    assert json.loads((source / "openclaw.json").read_text()) == config


@pytest.mark.parametrize("migrate_secrets", [False, True])
def test_mcp_credentials_require_explicit_import(tmp_path, migrate_secrets):
    mod = load_module()
    source = tmp_path / "source"
    source.mkdir()
    server = {"command": "fixture-server", "env": {"CUSTOM_KEY": "opaque-env"},
              "url": "https://fixture.invalid/mcp", "headers": {"X-Custom-Key": "opaque-header"},
              "auth": {"token": "opaque-auth"}, "timeout": 12}
    (source / "openclaw.json").write_text(json.dumps({"mcp": {"servers": {"fixture": server}}}))
    target = tmp_path / "target"
    report = mod.Migrator(source_root=source, target_root=target, execute=True,
                         workspace_target=None, overwrite=False, migrate_secrets=migrate_secrets,
                         output_dir=None, selected_options={"mcp-servers"}).migrate()
    actual = mod.load_yaml_file(target / "config.yaml")["mcp_servers"]["fixture"]
    assert actual["command"] == server["command"] and actual["timeout"] == 12
    for field in ("env", "headers", "auth"):
        if migrate_secrets:
            assert actual[field] == server[field]
        else:
            assert field not in actual
    if not migrate_secrets:
        assert any(i["kind"] == "mcp-servers" and "credential" in i["reason"].lower() for i in report["items"])
