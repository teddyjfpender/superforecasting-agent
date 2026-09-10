"""Migration preserves target settings while importing the gateway workspace."""

import json

import pytest

from test_openclaw_migration import load_module


@pytest.mark.parametrize(
    "existing,overwrite,execute,status",
    [(None, False, True, "migrated"), (None, False, False, "migrated"),
     ("/existing", False, True, "conflict"), ("/existing", True, True, "migrated"),
     ("/existing", True, False, "migrated"), ("/incoming", False, True, "skipped")],
)
def test_workspace_config_preserves_settings_and_backs_up(tmp_path, existing, overwrite, execute, status):
    mod = load_module()
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "openclaw.json").write_text(json.dumps({"agents": {"defaults": {"workspace": "/incoming"}}}))
    config_path = target / "config.yaml"
    initial = {"terminal": {"timeout": 17}, "display": {"skin": "forecast"}}
    if existing is not None:
        initial["terminal"]["cwd"] = existing
    mod.dump_yaml_file(config_path, initial)
    initial_bytes = config_path.read_bytes()
    migrator = mod.Migrator(source_root=source, target_root=target, execute=execute,
                           workspace_target=None, overwrite=overwrite, migrate_secrets=False, output_dir=None,
                           selected_options={"messaging-settings"})
    report = migrator.migrate()
    items = [i for i in report["items"] if i["kind"] == "messaging-settings" and i["destination"] == str(config_path)]
    assert len(items) == 1
    assert items[0]["status"] == status
    changed = execute and status == "migrated"
    expected = {**initial, "terminal": {**initial["terminal"], "cwd": "/incoming"}} if changed else initial
    assert mod.load_yaml_file(config_path) == expected
    assert not (target / ".env").exists()
    if changed:
        from pathlib import Path
        assert Path(items[0]["details"]["backup"]).read_bytes() == initial_bytes
    else:
        assert config_path.read_bytes() == initial_bytes


@pytest.mark.parametrize("invalid", ["terminal: [broken", "terminal: wrong-shape\n", "- not-a-mapping\n"])
def test_invalid_workspace_target_blocks_later_config_writes(tmp_path, invalid):
    mod = load_module()
    source, target = tmp_path / "source", tmp_path / "target"
    source.mkdir()
    target.mkdir()
    (source / "openclaw.json").write_text(json.dumps({"agents": {"defaults": {
        "workspace": "/incoming", "model": "provider/model"}}}))
    # Construct before injecting malformed YAML: constructor reads existing memory limits.
    migrator = mod.Migrator(source_root=source, target_root=target, execute=True,
                           workspace_target=None, overwrite=True, migrate_secrets=False, output_dir=None,
                           selected_options={"messaging-settings", "model-config"})
    config_path = target / "config.yaml"
    config_path.write_text(invalid)
    report = migrator.migrate()
    assert config_path.read_text() == invalid
    assert any(i["kind"] == "messaging-settings" and i["status"] == "error" for i in report["items"])
    assert any(i["kind"] == "model-config" and i["reason"] == mod.REASON_BLOCKED_BY_APPLY_CONFLICT
               for i in report["items"])
    assert not (target / ".env").exists()
